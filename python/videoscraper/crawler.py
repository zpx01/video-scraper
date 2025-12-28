"""
YouTube Graph Crawler - Random walk video discovery.

Crawls YouTube by following related videos in a random walk pattern,
discovering new videos at scale.

Features:
- Parallel random walks from multiple starting points
- Deduplication to avoid revisiting videos
- Configurable depth and breadth
- Optional downloading of discovered videos
- Checkpointing for resume
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

logger = logging.getLogger(__name__)


@dataclass
class VideoNode:
    """A video in the YouTube graph."""
    
    video_id: str
    url: str
    title: Optional[str] = None
    channel: Optional[str] = None
    duration: Optional[int] = None
    view_count: Optional[int] = None
    related_ids: List[str] = field(default_factory=list)
    discovered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    depth: int = 0  # Distance from seed video
    parent_id: Optional[str] = None  # Which video led us here
    
    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "url": self.url,
            "title": self.title,
            "channel": self.channel,
            "duration": self.duration,
            "view_count": self.view_count,
            "related_ids": self.related_ids,
            "discovered_at": self.discovered_at,
            "depth": self.depth,
            "parent_id": self.parent_id,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "VideoNode":
        return cls(**data)


@dataclass
class CrawlStats:
    """Statistics for the crawl."""
    
    videos_discovered: int = 0
    videos_processed: int = 0
    videos_downloaded: int = 0
    bytes_downloaded: int = 0
    errors: int = 0
    start_time: float = field(default_factory=time.time)
    
    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time
    
    @property
    def videos_per_second(self) -> float:
        if self.elapsed_seconds == 0:
            return 0
        return self.videos_processed / self.elapsed_seconds
    
    def __str__(self) -> str:
        return (
            f"Discovered: {self.videos_discovered}, "
            f"Processed: {self.videos_processed}, "
            f"Downloaded: {self.videos_downloaded}, "
            f"Errors: {self.errors}, "
            f"Rate: {self.videos_per_second:.1f} videos/sec"
        )


class YouTubeGraphExtractor:
    """
    Extracts video metadata and related videos from YouTube.
    
    Uses multiple methods to get related videos:
    1. YouTube's watch page HTML (contains related video data in JSON)
    2. YouTube's /next endpoint (internal API)
    3. yt-dlp for metadata
    """
    
    def __init__(self):
        try:
            import yt_dlp
            self._yt_dlp = yt_dlp
        except ImportError:
            raise ImportError("yt-dlp required: pip install yt-dlp")
        
        try:
            import requests
            self._requests = requests
        except ImportError:
            raise ImportError("requests required: pip install requests")
        
        self._session = self._requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
    
    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats."""
        patterns = [
            r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
            r'(?:embed/)([a-zA-Z0-9_-]{11})',
            r'(?:shorts/)([a-zA-Z0-9_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def get_video_info(self, video_id: str) -> Optional[VideoNode]:
        """Get video metadata and related videos."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Get metadata from yt-dlp
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        
        title = None
        channel = None
        duration = None
        view_count = None
        
        try:
            with self._yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info:
                    title = info.get("title")
                    channel = info.get("channel") or info.get("uploader")
                    duration = info.get("duration")
                    view_count = info.get("view_count")
        except Exception as e:
            logger.debug(f"yt-dlp error for {video_id}: {e}")
        
        # Get related videos by scraping the watch page
        related_ids = self._get_related_from_page(video_id)
        
        return VideoNode(
            video_id=video_id,
            url=url,
            title=title,
            channel=channel,
            duration=duration,
            view_count=view_count,
            related_ids=related_ids,
        )
    
    def _get_related_from_page(self, video_id: str) -> List[str]:
        """
        Extract related video IDs from YouTube watch page.
        
        YouTube embeds related video data in the page's initial JSON data.
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        related_ids = []
        
        try:
            response = self._session.get(url, timeout=15)
            response.raise_for_status()
            html = response.text
            
            # Method 1: Extract from ytInitialData JSON
            # YouTube embeds this in a script tag
            patterns = [
                r'var\s+ytInitialData\s*=\s*({.+?});',
                r'window\["ytInitialData"\]\s*=\s*({.+?});',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        related_ids = self._extract_video_ids_from_data(data)
                        if related_ids:
                            break
                    except json.JSONDecodeError:
                        continue
            
            # Method 2: Simple regex for video IDs in the page
            if not related_ids:
                # Find all video IDs in the page
                all_ids = set(re.findall(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', html))
                # Remove the current video
                all_ids.discard(video_id)
                related_ids = list(all_ids)
            
        except Exception as e:
            logger.debug(f"Error fetching related for {video_id}: {e}")
        
        return related_ids[:25]  # Limit to 25 related videos
    
    def _extract_video_ids_from_data(self, data: dict) -> List[str]:
        """Recursively extract video IDs from YouTube's JSON data."""
        video_ids = []
        
        def extract_recursive(obj):
            if isinstance(obj, dict):
                # Check for videoId field
                if "videoId" in obj:
                    vid = obj["videoId"]
                    if isinstance(vid, str) and len(vid) == 11:
                        video_ids.append(vid)
                
                # Check for watchEndpoint
                if "watchEndpoint" in obj:
                    endpoint = obj["watchEndpoint"]
                    if isinstance(endpoint, dict) and "videoId" in endpoint:
                        vid = endpoint["videoId"]
                        if isinstance(vid, str) and len(vid) == 11:
                            video_ids.append(vid)
                
                # Recurse into values
                for value in obj.values():
                    extract_recursive(value)
                    
            elif isinstance(obj, list):
                for item in obj:
                    extract_recursive(item)
        
        extract_recursive(data)
        
        # Deduplicate while preserving order
        seen = set()
        unique_ids = []
        for vid in video_ids:
            if vid not in seen:
                seen.add(vid)
                unique_ids.append(vid)
        
        return unique_ids
    
    def get_related_videos_fast(self, video_id: str) -> List[str]:
        """
        Fast extraction of related video IDs.
        
        Just gets related IDs without full metadata.
        """
        return self._get_related_from_page(video_id)


class YouTubeCrawler:
    """
    Parallel random walk crawler for YouTube.
    
    Discovers videos by following related video links in a graph traversal.
    
    Example:
        >>> crawler = YouTubeCrawler(
        ...     max_videos=10000,
        ...     num_workers=16,
        ...     download=True,
        ...     output_dir="./youtube_crawl",
        ... )
        >>> 
        >>> # Start from a seed video
        >>> crawler.add_seed("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        >>> 
        >>> # Or start from multiple seeds
        >>> crawler.add_seeds([
        ...     "https://www.youtube.com/watch?v=VIDEO1",
        ...     "https://www.youtube.com/watch?v=VIDEO2",
        ... ])
        >>> 
        >>> # Or start from random popular videos
        >>> crawler.add_random_seeds(count=10)
        >>> 
        >>> # Run the crawl
        >>> crawler.run()
        >>> 
        >>> # Export discovered videos
        >>> crawler.export("discovered_videos.json")
    """
    
    def __init__(
        self,
        max_videos: int = 1000,
        max_depth: int = 50,
        num_workers: int = 8,
        download: bool = False,
        output_dir: str = "./crawl_output",
        checkpoint_file: Optional[str] = None,
        checkpoint_interval: int = 100,
        random_walk_prob: float = 0.8,  # Probability of following random related
        rate_limit_per_worker: float = 1.0,  # Requests per second per worker
        on_discover: Optional[Callable[[VideoNode], None]] = None,
        on_download: Optional[Callable[[VideoNode, str], None]] = None,
    ):
        """
        Initialize the crawler.
        
        Args:
            max_videos: Maximum number of unique videos to discover
            max_depth: Maximum depth from seed videos
            num_workers: Number of parallel crawl workers
            download: Whether to download videos as they're discovered
            output_dir: Directory for downloads and checkpoints
            checkpoint_file: File for saving crawl state
            checkpoint_interval: Save checkpoint every N videos
            random_walk_prob: Probability of random walk (vs BFS)
            rate_limit_per_worker: Rate limit per worker
            on_discover: Callback when video is discovered
            on_download: Callback when video is downloaded
        """
        self.max_videos = max_videos
        self.max_depth = max_depth
        self.num_workers = num_workers
        self.download = download
        self.output_dir = Path(output_dir)
        self.checkpoint_file = checkpoint_file
        self.checkpoint_interval = checkpoint_interval
        self.random_walk_prob = random_walk_prob
        self.rate_limit_per_worker = rate_limit_per_worker
        self.on_discover = on_discover
        self.on_download = on_download
        
        # State
        self._extractor = YouTubeGraphExtractor()
        self._frontier: Queue = Queue()  # Videos to visit
        self._visited: Set[str] = set()  # Visited video IDs
        self._discovered: Dict[str, VideoNode] = {}  # All discovered videos
        self._lock = threading.Lock()
        self._stats = CrawlStats()
        self._running = False
        self._stop_event = threading.Event()
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load checkpoint if exists
        if checkpoint_file and os.path.exists(checkpoint_file):
            self._load_checkpoint()
    
    def add_seed(self, url: str) -> bool:
        """Add a seed video URL to start crawling from."""
        video_id = self._extractor.extract_video_id(url)
        if video_id and video_id not in self._visited:
            self._frontier.put((video_id, 0, None))  # (id, depth, parent)
            logger.info(f"Added seed: {video_id}")
            return True
        return False
    
    def add_seeds(self, urls: List[str]) -> int:
        """Add multiple seed URLs."""
        count = sum(1 for url in urls if self.add_seed(url))
        logger.info(f"Added {count} seeds")
        return count
    
    def add_random_seeds(self, count: int = 10) -> int:
        """
        Add random seed videos by searching for popular/trending content.
        """
        # Popular search queries to find diverse seeds
        queries = [
            "music video 2024",
            "funny videos",
            "cooking tutorial",
            "tech review",
            "travel vlog",
            "gaming",
            "science documentary",
            "sports highlights",
            "news today",
            "educational",
            "nature documentary",
            "movie trailer",
            "podcast",
            "interview",
            "tutorial",
        ]
        
        import yt_dlp
        
        added = 0
        random.shuffle(queries)
        
        for query in queries[:count]:
            try:
                ydl_opts = {
                    "quiet": True,
                    "extract_flat": True,
                    "playlist_items": "1-3",  # Get top 3 results
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    results = ydl.extract_info(f"ytsearch3:{query}", download=False)
                    
                    for entry in results.get("entries", []):
                        if entry and entry.get("id"):
                            if self.add_seed(f"https://youtube.com/watch?v={entry['id']}"):
                                added += 1
                                if added >= count:
                                    return added
                                    
            except Exception as e:
                logger.debug(f"Error searching '{query}': {e}")
        
        return added
    
    def _worker(self, worker_id: int):
        """Worker thread that processes videos from the frontier."""
        logger.info(f"Worker {worker_id} started")
        
        delay = 1.0 / self.rate_limit_per_worker
        
        while not self._stop_event.is_set():
            # Check if we've reached the limit
            with self._lock:
                if len(self._discovered) >= self.max_videos:
                    break
            
            try:
                # Get next video from frontier
                video_id, depth, parent_id = self._frontier.get(timeout=5)
            except Empty:
                # No work available, check if others might add more
                if self._frontier.empty():
                    time.sleep(1)
                    if self._frontier.empty():
                        break
                continue
            
            # Skip if already visited or too deep
            with self._lock:
                if video_id in self._visited:
                    continue
                if depth > self.max_depth:
                    continue
                self._visited.add(video_id)
            
            # Rate limiting
            time.sleep(delay)
            
            # Extract video info
            try:
                node = self._extractor.get_video_info(video_id)
                
                if node:
                    node.depth = depth
                    node.parent_id = parent_id
                    
                    with self._lock:
                        self._discovered[video_id] = node
                        self._stats.videos_discovered += 1
                        self._stats.videos_processed += 1
                    
                    # Callback
                    if self.on_discover:
                        try:
                            self.on_discover(node)
                        except Exception as e:
                            logger.error(f"on_discover callback error: {e}")
                    
                    # Download if enabled
                    if self.download:
                        self._download_video(node)
                    
                    # Add related videos to frontier
                    self._add_related_to_frontier(node, depth)
                    
                    # Checkpoint
                    if (
                        self.checkpoint_file
                        and self._stats.videos_processed % self.checkpoint_interval == 0
                    ):
                        self._save_checkpoint()
                    
                    # Log progress
                    if self._stats.videos_processed % 10 == 0:
                        logger.info(f"Worker {worker_id}: {self._stats}")
                else:
                    with self._lock:
                        self._stats.errors += 1
                        
            except Exception as e:
                logger.error(f"Worker {worker_id} error processing {video_id}: {e}")
                with self._lock:
                    self._stats.errors += 1
        
        logger.info(f"Worker {worker_id} finished")
    
    def _add_related_to_frontier(self, node: VideoNode, current_depth: int):
        """Add related videos to the frontier."""
        if not node.related_ids:
            return
        
        # Random walk: pick random subset of related videos
        if random.random() < self.random_walk_prob:
            # Random walk: pick 1-3 random related videos
            num_to_add = random.randint(1, min(3, len(node.related_ids)))
            related = random.sample(node.related_ids, num_to_add)
        else:
            # BFS: add all related videos
            related = node.related_ids
        
        for related_id in related:
            with self._lock:
                if related_id not in self._visited:
                    self._frontier.put((related_id, current_depth + 1, node.video_id))
    
    def _download_video(self, node: VideoNode):
        """Download a video."""
        try:
            from videoscraper import YouTubeScraper
            
            scraper = YouTubeScraper(
                output_dir=str(self.output_dir / "videos"),
                quality="720p",
                format="mp4",
            )
            
            result = scraper.download(node.url)
            
            if result.success:
                with self._lock:
                    self._stats.videos_downloaded += 1
                    if result.output_path:
                        size = os.path.getsize(result.output_path)
                        self._stats.bytes_downloaded += size
                
                if self.on_download:
                    try:
                        self.on_download(node, result.output_path)
                    except Exception as e:
                        logger.error(f"on_download callback error: {e}")
                        
        except Exception as e:
            logger.error(f"Download error for {node.video_id}: {e}")
    
    def run(self) -> CrawlStats:
        """
        Run the crawler until max_videos reached or frontier exhausted.
        
        Returns:
            CrawlStats with crawl statistics
        """
        if self._frontier.empty():
            logger.warning("No seeds in frontier! Add seeds first.")
            return self._stats
        
        self._running = True
        self._stop_event.clear()
        self._stats = CrawlStats()
        
        logger.info(f"Starting crawl with {self.num_workers} workers")
        logger.info(f"Target: {self.max_videos} videos, max depth: {self.max_depth}")
        
        # Start workers
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = [
                executor.submit(self._worker, i)
                for i in range(self.num_workers)
            ]
            
            # Wait for all workers
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Worker error: {e}")
        
        self._running = False
        
        # Final checkpoint
        if self.checkpoint_file:
            self._save_checkpoint()
        
        logger.info(f"Crawl complete: {self._stats}")
        return self._stats
    
    def stop(self):
        """Stop the crawler gracefully."""
        logger.info("Stopping crawler...")
        self._stop_event.set()
    
    def export(self, path: str, format: str = "auto"):
        """
        Export discovered videos to a file.
        
        Args:
            path: Output file path
            format: 'json', 'jsonl', 'csv', or 'auto'
        """
        path = Path(path)
        
        if format == "auto":
            format = path.suffix.lstrip(".") or "json"
        
        if format == "json":
            with open(path, "w") as f:
                json.dump(
                    [node.to_dict() for node in self._discovered.values()],
                    f,
                    indent=2,
                )
        
        elif format == "jsonl":
            with open(path, "w") as f:
                for node in self._discovered.values():
                    f.write(json.dumps(node.to_dict()) + "\n")
        
        elif format == "csv":
            import csv
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "video_id", "url", "title", "channel", "duration",
                    "view_count", "depth", "parent_id", "discovered_at"
                ])
                for node in self._discovered.values():
                    writer.writerow([
                        node.video_id, node.url, node.title, node.channel,
                        node.duration, node.view_count, node.depth,
                        node.parent_id, node.discovered_at
                    ])
        
        logger.info(f"Exported {len(self._discovered)} videos to {path}")
    
    def _save_checkpoint(self):
        """Save crawl state to checkpoint file."""
        if not self.checkpoint_file:
            return
        
        checkpoint = {
            "visited": list(self._visited),
            "discovered": {k: v.to_dict() for k, v in self._discovered.items()},
            "stats": {
                "videos_discovered": self._stats.videos_discovered,
                "videos_processed": self._stats.videos_processed,
                "videos_downloaded": self._stats.videos_downloaded,
                "bytes_downloaded": self._stats.bytes_downloaded,
                "errors": self._stats.errors,
            },
            "timestamp": datetime.now().isoformat(),
        }
        
        with open(self.checkpoint_file, "w") as f:
            json.dump(checkpoint, f)
        
        logger.debug(f"Saved checkpoint: {len(self._discovered)} videos")
    
    def _load_checkpoint(self):
        """Load crawl state from checkpoint file."""
        if not self.checkpoint_file or not os.path.exists(self.checkpoint_file):
            return
        
        try:
            with open(self.checkpoint_file, "r") as f:
                checkpoint = json.load(f)
            
            self._visited = set(checkpoint.get("visited", []))
            self._discovered = {
                k: VideoNode.from_dict(v)
                for k, v in checkpoint.get("discovered", {}).items()
            }
            
            stats = checkpoint.get("stats", {})
            self._stats.videos_discovered = stats.get("videos_discovered", 0)
            self._stats.videos_processed = stats.get("videos_processed", 0)
            self._stats.videos_downloaded = stats.get("videos_downloaded", 0)
            self._stats.bytes_downloaded = stats.get("bytes_downloaded", 0)
            self._stats.errors = stats.get("errors", 0)
            
            logger.info(
                f"Loaded checkpoint: {len(self._discovered)} videos, "
                f"{len(self._visited)} visited"
            )
            
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
    
    @property
    def discovered_videos(self) -> List[VideoNode]:
        """Get all discovered videos."""
        return list(self._discovered.values())
    
    @property
    def stats(self) -> CrawlStats:
        """Get current statistics."""
        return self._stats


def main():
    """Demo crawl."""
    import argparse
    
    parser = argparse.ArgumentParser(description="YouTube Graph Crawler")
    parser.add_argument("--seeds", nargs="*", help="Seed video URLs")
    parser.add_argument("--random-seeds", type=int, default=5, help="Number of random seeds")
    parser.add_argument("--max-videos", type=int, default=100, help="Max videos to discover")
    parser.add_argument("--workers", type=int, default=4, help="Number of workers")
    parser.add_argument("--download", action="store_true", help="Download videos")
    parser.add_argument("--output", default="./crawl_output", help="Output directory")
    parser.add_argument("--export", default="discovered.json", help="Export file")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    crawler = YouTubeCrawler(
        max_videos=args.max_videos,
        num_workers=args.workers,
        download=args.download,
        output_dir=args.output,
        checkpoint_file=f"{args.output}/checkpoint.json",
    )
    
    # Add seeds
    if args.seeds:
        crawler.add_seeds(args.seeds)
    else:
        crawler.add_random_seeds(args.random_seeds)
    
    # Run
    try:
        stats = crawler.run()
        print(f"\nCrawl complete: {stats}")
        
        # Export
        crawler.export(args.export)
        print(f"Exported to: {args.export}")
        
    except KeyboardInterrupt:
        print("\nInterrupted, saving...")
        crawler.stop()
        crawler.export(args.export)


if __name__ == "__main__":
    main()

