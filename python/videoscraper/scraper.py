"""
High-level Scraper API for easy video scraping.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Union

from videoscraper._core import (
    DownloadResult,
    PyDownloadManager,
    PyPipeline,
    PyVideoExtractor,
    ScraperConfig,
    StorageConfig,
    VideoFilter,
    VideoInfo,
)


@dataclass
class ScrapeResult:
    """Result of a scraping operation."""
    
    url: str
    success: bool
    output_path: Optional[str] = None
    video_info: Optional[VideoInfo] = None
    download_result: Optional[DownloadResult] = None
    error: Optional[str] = None
    
    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"ScrapeResult({status} {self.url})"


class Scraper:
    """
    High-level API for scraping video content.
    
    Example:
        >>> scraper = Scraper(output_dir="./videos")
        >>> 
        >>> # Scrape a single URL
        >>> result = scraper.scrape("https://example.com/video")
        >>> print(f"Downloaded to: {result.output_path}")
        >>> 
        >>> # Scrape multiple URLs
        >>> results = scraper.scrape_many([
        ...     "https://example.com/video1",
        ...     "https://example.com/video2",
        ... ])
        >>> 
        >>> # With filters
        >>> scraper = Scraper(
        ...     output_dir="./videos",
        ...     filter=VideoFilter.hd(),  # Only 720p+
        ... )
    """
    
    def __init__(
        self,
        output_dir: Union[str, Path] = "./downloads",
        config: Optional[ScraperConfig] = None,
        filter: Optional[VideoFilter] = None,
        on_progress: Optional[Callable[[str, float], None]] = None,
    ):
        """
        Initialize the scraper.
        
        Args:
            output_dir: Directory to save downloaded videos
            config: Scraper configuration (uses defaults if not provided)
            filter: Video filter for quality/format selection
            on_progress: Callback for progress updates (url, percentage)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.config = config or ScraperConfig()
        self.filter = filter
        self.on_progress = on_progress
        
        self._extractor = PyVideoExtractor(self.config)
        self._downloader = PyDownloadManager(self.config)
    
    def extract(self, url: str) -> List[VideoInfo]:
        """
        Extract video information from a URL without downloading.
        
        Args:
            url: URL to extract videos from
            
        Returns:
            List of VideoInfo objects
        """
        return self._extractor.extract_from_url(url)
    
    def scrape(
        self,
        url: str,
        filename: Optional[str] = None,
    ) -> ScrapeResult:
        """
        Scrape and download a video from a URL.
        
        Args:
            url: URL to scrape
            filename: Custom filename (auto-generated if not provided)
            
        Returns:
            ScrapeResult with download information
        """
        try:
            # Extract videos
            videos = self._extractor.extract_from_url(url)
            
            if not videos:
                return ScrapeResult(
                    url=url,
                    success=False,
                    error="No videos found at URL",
                )
            
            # Apply filter if set
            if self.filter:
                videos = [v for v in videos if self.filter.matches(v)]
                if not videos:
                    return ScrapeResult(
                        url=url,
                        success=False,
                        error="No videos matched filter criteria",
                    )
            
            # Select first/best video
            video = videos[0]
            
            # Generate filename
            if not filename:
                ext = video.format or "mp4"
                safe_title = "".join(
                    c for c in (video.title or "video")[:50]
                    if c.isalnum() or c in " -_"
                ).strip()
                filename = f"{safe_title}.{ext}"
            
            output_path = self.output_dir / filename
            
            # Download
            result = self._downloader.download(video.url, str(output_path))
            
            return ScrapeResult(
                url=url,
                success=True,
                output_path=str(output_path),
                video_info=video,
                download_result=result,
            )
            
        except Exception as e:
            return ScrapeResult(
                url=url,
                success=False,
                error=str(e),
            )
    
    def scrape_many(
        self,
        urls: List[str],
        concurrency: int = 8,
    ) -> List[ScrapeResult]:
        """
        Scrape multiple URLs concurrently.
        
        Args:
            urls: List of URLs to scrape
            concurrency: Number of concurrent downloads
            
        Returns:
            List of ScrapeResult objects
        """
        results = []
        for url in urls:
            result = self.scrape(url)
            results.append(result)
        return results
    
    def iter_scrape(
        self,
        urls: List[str],
    ) -> Iterator[ScrapeResult]:
        """
        Iterate over scraping results as they complete.
        
        Args:
            urls: List of URLs to scrape
            
        Yields:
            ScrapeResult objects as they complete
        """
        for url in urls:
            yield self.scrape(url)


class AsyncScraper:
    """
    Async version of the Scraper for use with asyncio.
    
    Example:
        >>> import asyncio
        >>> 
        >>> async def main():
        ...     scraper = AsyncScraper(output_dir="./videos")
        ...     result = await scraper.scrape("https://example.com/video")
        ...     print(result)
        >>> 
        >>> asyncio.run(main())
    """
    
    def __init__(
        self,
        output_dir: Union[str, Path] = "./downloads",
        config: Optional[ScraperConfig] = None,
        filter: Optional[VideoFilter] = None,
    ):
        """Initialize the async scraper."""
        self.output_dir = Path(output_dir)
        self.config = config or ScraperConfig()
        self.filter = filter
        self._sync_scraper = Scraper(output_dir, config, filter)
    
    async def extract(self, url: str) -> List[VideoInfo]:
        """Extract video information from a URL."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_scraper.extract, url)
    
    async def scrape(
        self,
        url: str,
        filename: Optional[str] = None,
    ) -> ScrapeResult:
        """Scrape and download a video from a URL."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_scraper.scrape, url, filename
        )
    
    async def scrape_many(
        self,
        urls: List[str],
        concurrency: int = 8,
    ) -> List[ScrapeResult]:
        """Scrape multiple URLs concurrently."""
        import asyncio
        
        semaphore = asyncio.Semaphore(concurrency)
        
        async def scrape_with_semaphore(url: str) -> ScrapeResult:
            async with semaphore:
                return await self.scrape(url)
        
        tasks = [scrape_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks)

