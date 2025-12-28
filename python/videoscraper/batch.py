"""
Batch scraping for large-scale video collection.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Dict, Iterator, List, Optional, TextIO, Union

from videoscraper._core import (
    PyPipeline,
    ScraperConfig,
    StorageConfig,
    ScrapeJob,
    VideoFilter,
    PipelineStats,
)
from videoscraper.scraper import Scraper, ScrapeResult

logger = logging.getLogger(__name__)


@dataclass
class BatchProgress:
    """Progress information for batch scraping."""
    
    total: int
    completed: int
    failed: int
    in_progress: int
    bytes_downloaded: int
    elapsed_seconds: float
    
    @property
    def percent_complete(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.completed / self.total) * 100
    
    @property
    def success_rate(self) -> float:
        processed = self.completed + self.failed
        if processed == 0:
            return 0.0
        return (self.completed / processed) * 100
    
    @property
    def download_speed_mbps(self) -> float:
        if self.elapsed_seconds == 0:
            return 0.0
        return (self.bytes_downloaded / 1_000_000) / self.elapsed_seconds
    
    def __repr__(self) -> str:
        return (
            f"BatchProgress({self.completed}/{self.total} complete, "
            f"{self.failed} failed, {self.download_speed_mbps:.1f} MB/s)"
        )


@dataclass
class BatchConfig:
    """Configuration for batch scraping."""
    
    # Concurrency settings
    max_concurrent: int = 32
    max_per_domain: int = 4
    
    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 5.0
    
    # Rate limiting
    requests_per_second: float = 10.0
    
    # Output settings
    output_dir: str = "./downloads"
    organize_by_domain: bool = True
    
    # Checkpointing
    checkpoint_file: Optional[str] = None
    checkpoint_interval: int = 100
    
    # Logging
    log_file: Optional[str] = None
    verbose: bool = False
    
    # Filtering
    video_filter: Optional[VideoFilter] = None
    
    # Callbacks
    on_complete: Optional[Callable[[ScrapeResult], None]] = None
    on_error: Optional[Callable[[str, Exception], None]] = None
    on_progress: Optional[Callable[[BatchProgress], None]] = None


class BatchScraper:
    """
    High-performance batch scraper for large-scale video collection.
    
    Features:
    - Petabyte-scale scraping with checkpointing
    - Automatic resume from failures
    - Progress tracking and reporting
    - Domain-based rate limiting
    - Organized output structure
    
    Example:
        >>> from videoscraper import BatchScraper, BatchConfig
        >>> 
        >>> config = BatchConfig(
        ...     max_concurrent=64,
        ...     output_dir="./videos",
        ...     checkpoint_file="./checkpoint.json",
        ... )
        >>> 
        >>> scraper = BatchScraper(config)
        >>> 
        >>> # Add URLs from file
        >>> scraper.add_from_file("urls.txt")
        >>> 
        >>> # Or add URLs directly
        >>> scraper.add_urls([
        ...     "https://example.com/video1",
        ...     "https://example.com/video2",
        ... ])
        >>> 
        >>> # Run the batch
        >>> results = scraper.run()
        >>> 
        >>> # Export results
        >>> scraper.export_results("results.csv")
    """
    
    def __init__(
        self,
        config: Optional[BatchConfig] = None,
        scraper_config: Optional[ScraperConfig] = None,
        storage_config: Optional[StorageConfig] = None,
    ):
        """
        Initialize the batch scraper.
        
        Args:
            config: Batch configuration
            scraper_config: Core scraper configuration
            storage_config: Storage backend configuration
        """
        self.config = config or BatchConfig()
        self.scraper_config = scraper_config or ScraperConfig.high_performance()
        self.storage_config = storage_config or StorageConfig.local(
            self.config.output_dir
        )
        
        # Apply batch config to scraper config
        self.scraper_config.max_concurrent_downloads = self.config.max_concurrent
        self.scraper_config.max_requests_per_domain = self.config.max_per_domain
        self.scraper_config.rate_limit_per_second = self.config.requests_per_second
        self.scraper_config.max_retries = self.config.max_retries
        
        # State
        self._urls: List[str] = []
        self._results: List[ScrapeResult] = []
        self._failed: Dict[str, str] = {}
        self._completed: set = set()
        self._start_time: Optional[float] = None
        self._lock = threading.Lock()
        
        # Load checkpoint if exists
        if self.config.checkpoint_file and os.path.exists(self.config.checkpoint_file):
            self._load_checkpoint()
        
        # Setup logging
        if self.config.log_file:
            handler = logging.FileHandler(self.config.log_file)
            handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            ))
            logger.addHandler(handler)
        
        if self.config.verbose:
            logger.setLevel(logging.DEBUG)
    
    def add_url(self, url: str) -> None:
        """Add a single URL to the batch."""
        if url not in self._completed:
            self._urls.append(url)
    
    def add_urls(self, urls: List[str]) -> None:
        """Add multiple URLs to the batch."""
        for url in urls:
            self.add_url(url)
    
    def add_from_file(
        self,
        path: Union[str, Path],
        column: Optional[str] = None,
    ) -> int:
        """
        Add URLs from a file.
        
        Supports:
        - Plain text (one URL per line)
        - CSV (specify column name)
        - JSON (list of URLs or objects with 'url' field)
        
        Args:
            path: Path to the file
            column: Column name for CSV files
            
        Returns:
            Number of URLs added
        """
        path = Path(path)
        initial_count = len(self._urls)
        
        with open(path, "r") as f:
            if path.suffix == ".csv":
                reader = csv.DictReader(f)
                col = column or "url"
                for row in reader:
                    if col in row and row[col]:
                        self.add_url(row[col].strip())
            
            elif path.suffix == ".json":
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            self.add_url(item.strip())
                        elif isinstance(item, dict) and "url" in item:
                            self.add_url(item["url"].strip())
            
            else:  # Plain text
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self.add_url(line)
        
        added = len(self._urls) - initial_count
        logger.info(f"Added {added} URLs from {path}")
        return added
    
    def run(
        self,
        max_urls: Optional[int] = None,
    ) -> List[ScrapeResult]:
        """
        Run the batch scraping job.
        
        Args:
            max_urls: Maximum number of URLs to process (all if not set)
            
        Returns:
            List of ScrapeResult objects
        """
        urls_to_process = self._urls[:max_urls] if max_urls else self._urls
        self._start_time = time.time()
        
        logger.info(f"Starting batch scrape of {len(urls_to_process)} URLs")
        
        # Create scraper
        scraper = Scraper(
            output_dir=self.config.output_dir,
            config=self.scraper_config,
            filter=self.config.video_filter,
        )
        
        # Process URLs
        processed = 0
        for url in urls_to_process:
            if url in self._completed:
                continue
            
            result = scraper.scrape(url)
            
            with self._lock:
                self._results.append(result)
                if result.success:
                    self._completed.add(url)
                else:
                    self._failed[url] = result.error or "Unknown error"
                
                processed += 1
                
                # Callbacks
                if result.success and self.config.on_complete:
                    self.config.on_complete(result)
                elif not result.success and self.config.on_error:
                    self.config.on_error(url, Exception(result.error))
                
                # Progress callback
                if self.config.on_progress and processed % 10 == 0:
                    self.config.on_progress(self.progress())
                
                # Checkpoint
                if (
                    self.config.checkpoint_file
                    and processed % self.config.checkpoint_interval == 0
                ):
                    self._save_checkpoint()
        
        # Final checkpoint
        if self.config.checkpoint_file:
            self._save_checkpoint()
        
        elapsed = time.time() - self._start_time
        logger.info(
            f"Batch complete: {len(self._completed)} succeeded, "
            f"{len(self._failed)} failed in {elapsed:.1f}s"
        )
        
        return self._results
    
    def progress(self) -> BatchProgress:
        """Get current progress information."""
        elapsed = 0.0
        if self._start_time:
            elapsed = time.time() - self._start_time
        
        total_bytes = sum(
            r.download_result.size_bytes if r.download_result else 0
            for r in self._results
            if r.success
        )
        
        return BatchProgress(
            total=len(self._urls),
            completed=len(self._completed),
            failed=len(self._failed),
            in_progress=0,  # Sync implementation
            bytes_downloaded=total_bytes,
            elapsed_seconds=elapsed,
        )
    
    def export_results(
        self,
        path: Union[str, Path],
        format: str = "auto",
    ) -> None:
        """
        Export results to a file.
        
        Args:
            path: Output file path
            format: Output format ('csv', 'json', or 'auto' to detect from extension)
        """
        path = Path(path)
        
        if format == "auto":
            format = path.suffix.lstrip(".") or "csv"
        
        if format == "csv":
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "url", "success", "output_path", "size_bytes",
                    "duration_secs", "error"
                ])
                for r in self._results:
                    writer.writerow([
                        r.url,
                        r.success,
                        r.output_path or "",
                        r.download_result.size_bytes if r.download_result else "",
                        r.download_result.duration_secs if r.download_result else "",
                        r.error or "",
                    ])
        
        elif format == "json":
            data = []
            for r in self._results:
                data.append({
                    "url": r.url,
                    "success": r.success,
                    "output_path": r.output_path,
                    "size_bytes": r.download_result.size_bytes if r.download_result else None,
                    "duration_secs": r.download_result.duration_secs if r.download_result else None,
                    "error": r.error,
                })
            
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        logger.info(f"Exported {len(self._results)} results to {path}")
    
    def _save_checkpoint(self) -> None:
        """Save checkpoint to disk."""
        if not self.config.checkpoint_file:
            return
        
        checkpoint = {
            "completed": list(self._completed),
            "failed": self._failed,
            "timestamp": datetime.now().isoformat(),
        }
        
        with open(self.config.checkpoint_file, "w") as f:
            json.dump(checkpoint, f)
        
        logger.debug(f"Saved checkpoint: {len(self._completed)} completed")
    
    def _load_checkpoint(self) -> None:
        """Load checkpoint from disk."""
        if not self.config.checkpoint_file:
            return
        
        try:
            with open(self.config.checkpoint_file, "r") as f:
                checkpoint = json.load(f)
            
            self._completed = set(checkpoint.get("completed", []))
            self._failed = checkpoint.get("failed", {})
            
            logger.info(
                f"Loaded checkpoint: {len(self._completed)} completed, "
                f"{len(self._failed)} failed"
            )
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
    
    def retry_failed(self) -> List[ScrapeResult]:
        """Retry all failed URLs."""
        failed_urls = list(self._failed.keys())
        self._failed.clear()
        self._urls = failed_urls
        return self.run()
    
    @property
    def results(self) -> List[ScrapeResult]:
        """Get all results."""
        return self._results.copy()
    
    @property
    def failed_urls(self) -> Dict[str, str]:
        """Get failed URLs with error messages."""
        return self._failed.copy()

