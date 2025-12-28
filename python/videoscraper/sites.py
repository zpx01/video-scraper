"""
Site-specific video scrapers with optimized extraction.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from videoscraper._core import (
    PyDownloadManager,
    PyVideoExtractor,
    ScraperConfig,
    VideoInfo,
    VideoFormat,
)
from videoscraper.scraper import Scraper, ScrapeResult

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    """Rich video metadata from site-specific extraction."""
    
    id: str
    title: str
    description: Optional[str] = None
    duration: Optional[int] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    upload_date: Optional[str] = None
    uploader: Optional[str] = None
    uploader_id: Optional[str] = None
    channel: Optional[str] = None
    channel_id: Optional[str] = None
    thumbnail: Optional[str] = None
    categories: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    formats: Optional[List[Dict[str, Any]]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class SiteExtractor(ABC):
    """Base class for site-specific extractors."""
    
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this extractor can handle the given URL."""
        pass
    
    @abstractmethod
    def extract(self, url: str) -> VideoMetadata:
        """Extract video metadata from the URL."""
        pass
    
    @abstractmethod
    def get_download_url(
        self,
        url: str,
        quality: Optional[str] = None,
        format: Optional[str] = None,
    ) -> str:
        """Get the direct download URL for the video."""
        pass


class GenericScraper(Scraper):
    """
    Generic scraper that works with any website.
    
    Uses HTML parsing to find video elements and direct links.
    Best for simple video hosting sites.
    
    Example:
        >>> scraper = GenericScraper(output_dir="./videos")
        >>> result = scraper.scrape("https://example.com/video.html")
    """
    
    def __init__(
        self,
        output_dir: Union[str, Path] = "./downloads",
        config: Optional[ScraperConfig] = None,
    ):
        super().__init__(output_dir=output_dir, config=config)


class YouTubeScraper:
    """
    YouTube-optimized scraper using yt-dlp for extraction.
    
    Supports:
    - Individual videos
    - Playlists
    - Channels
    - Search results
    - Quality selection
    - Format selection
    - Metadata extraction
    
    Example:
        >>> scraper = YouTubeScraper(output_dir="./youtube")
        >>> 
        >>> # Download a video
        >>> result = scraper.download("https://youtube.com/watch?v=VIDEO_ID")
        >>> 
        >>> # Download a playlist
        >>> results = scraper.download_playlist(
        ...     "https://youtube.com/playlist?list=PLAYLIST_ID"
        ... )
        >>> 
        >>> # Get video info without downloading
        >>> info = scraper.get_info("https://youtube.com/watch?v=VIDEO_ID")
    
    Note:
        Requires yt-dlp to be installed: pip install yt-dlp
    """
    
    def __init__(
        self,
        output_dir: Union[str, Path] = "./downloads",
        quality: str = "best",
        format: str = "mp4",
        extract_audio: bool = False,
        cookies_file: Optional[str] = None,
        rate_limit: Optional[str] = None,
    ):
        """
        Initialize the YouTube scraper.
        
        Args:
            output_dir: Directory to save downloaded videos
            quality: Video quality ('best', '1080p', '720p', '480p', etc.)
            format: Output format ('mp4', 'webm', 'mkv')
            extract_audio: If True, extract audio only
            cookies_file: Path to cookies file for authenticated downloads
            rate_limit: Rate limit for downloads (e.g., '50M' for 50 MB/s)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.quality = quality
        self.format = format
        self.extract_audio = extract_audio
        self.cookies_file = cookies_file
        self.rate_limit = rate_limit
        
        # Check if yt-dlp is available
        self._ytdlp_path = shutil.which("yt-dlp")
        if not self._ytdlp_path:
            try:
                import yt_dlp
                self._use_python_api = True
            except ImportError:
                raise RuntimeError(
                    "yt-dlp is required for YouTube scraping. "
                    "Install it with: pip install yt-dlp"
                )
        else:
            self._use_python_api = False
    
    def _get_format_string(self) -> str:
        """Get the yt-dlp format string optimized for compatibility."""
        if self.extract_audio:
            return "bestaudio[ext=m4a]/bestaudio/best"
        
        # Prefer H.264 (avc1) for QuickTime/iOS compatibility
        # VP9/AV1 won't play in QuickTime
        if self.quality == "best":
            return (
                # Prefer H.264 video + AAC audio for max compatibility
                "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[acodec^=mp4a][ext=m4a]/"
                "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                # Fallback to any H.264
                "bestvideo[vcodec^=avc1]+bestaudio/"
                # Last resort: best available (may need re-encoding)
                "best[ext=mp4]/best"
            )
        
        # Parse quality (e.g., "1080p" -> 1080)
        height = int(self.quality.rstrip("p"))
        return (
            # H.264 at specified quality
            f"bestvideo[height<={height}][vcodec^=avc1][ext=mp4]+bestaudio[acodec^=mp4a][ext=m4a]/"
            f"bestvideo[height<={height}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[height<={height}][vcodec^=avc1]+bestaudio/"
            # Fallback
            f"best[height<={height}][ext=mp4]/best[height<={height}]/best"
        )
    
    def _build_ytdlp_opts(self, output_template: str) -> Dict[str, Any]:
        """Build yt-dlp options dictionary."""
        opts = {
            "format": self._get_format_string(),
            "outtmpl": output_template,
            "merge_output_format": self.format,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }
        
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        
        if self.rate_limit:
            opts["ratelimit"] = self._parse_rate_limit(self.rate_limit)
        
        return opts
    
    def _parse_rate_limit(self, rate: str) -> int:
        """Parse rate limit string to bytes per second."""
        rate = rate.upper()
        multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3}
        
        for suffix, mult in multipliers.items():
            if rate.endswith(suffix):
                return int(float(rate[:-1]) * mult)
        
        return int(rate)
    
    def get_info(self, url: str) -> VideoMetadata:
        """
        Get video information without downloading.
        
        Args:
            url: YouTube video URL
            
        Returns:
            VideoMetadata object
        """
        if self._use_python_api:
            return self._get_info_python(url)
        else:
            return self._get_info_cli(url)
    
    def _get_info_python(self, url: str) -> VideoMetadata:
        """Get info using yt-dlp Python API."""
        import yt_dlp
        
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": False}) as ydl:
            info = ydl.extract_info(url, download=False)
        
        return self._parse_info(info)
    
    def _get_info_cli(self, url: str) -> VideoMetadata:
        """Get info using yt-dlp CLI."""
        cmd = [
            self._ytdlp_path,
            "--dump-json",
            "--no-download",
            url,
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {result.stderr}")
        
        info = json.loads(result.stdout)
        return self._parse_info(info)
    
    def _parse_info(self, info: Dict[str, Any]) -> VideoMetadata:
        """Parse yt-dlp info dict into VideoMetadata."""
        return VideoMetadata(
            id=info.get("id", ""),
            title=info.get("title", ""),
            description=info.get("description"),
            duration=info.get("duration"),
            view_count=info.get("view_count"),
            like_count=info.get("like_count"),
            upload_date=info.get("upload_date"),
            uploader=info.get("uploader"),
            uploader_id=info.get("uploader_id"),
            channel=info.get("channel"),
            channel_id=info.get("channel_id"),
            thumbnail=info.get("thumbnail"),
            categories=info.get("categories"),
            tags=info.get("tags"),
            formats=[
                {
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "width": f.get("width"),
                    "height": f.get("height"),
                    "fps": f.get("fps"),
                    "vcodec": f.get("vcodec"),
                    "acodec": f.get("acodec"),
                    "filesize": f.get("filesize"),
                }
                for f in info.get("formats", [])
            ],
        )
    
    def download(
        self,
        url: str,
        filename: Optional[str] = None,
    ) -> ScrapeResult:
        """
        Download a video from YouTube.
        
        Args:
            url: YouTube video URL
            filename: Custom filename (auto-generated if not provided)
            
        Returns:
            ScrapeResult
        """
        try:
            # Get info first
            info = self.get_info(url)
            
            # Generate output template
            if filename:
                output_path = self.output_dir / filename
            else:
                safe_title = re.sub(r'[<>:"/\\|?*]', "_", info.title)[:100]
                output_path = self.output_dir / f"{safe_title}.{self.format}"
            
            output_template = str(output_path)
            
            # Download
            if self._use_python_api:
                self._download_python(url, output_template)
            else:
                self._download_cli(url, output_template)
            
            # Find the actual output file (yt-dlp may modify the name)
            actual_path = self._find_output_file(output_path)
            
            # Create a simple info object (VideoInfo is a Rust struct)
            from videoscraper.scraper import ScrapeResult as PyScrapeResult
            
            return ScrapeResult(
                url=url,
                success=True,
                output_path=str(actual_path) if actual_path else str(output_path),
                video_info=None,  # VideoInfo is Rust-only, store metadata separately
            )
            
        except Exception as e:
            logger.error(f"YouTube download failed: {e}")
            return ScrapeResult(
                url=url,
                success=False,
                error=str(e),
            )
    
    def _download_python(self, url: str, output_template: str) -> None:
        """Download using yt-dlp Python API."""
        import yt_dlp
        
        opts = self._build_ytdlp_opts(output_template)
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    
    def _download_cli(self, url: str, output_template: str) -> None:
        """Download using yt-dlp CLI."""
        cmd = [
            self._ytdlp_path,
            "-f", self._get_format_string(),
            "-o", output_template,
            "--merge-output-format", self.format,
        ]
        
        if self.cookies_file:
            cmd.extend(["--cookies", self.cookies_file])
        
        if self.rate_limit:
            cmd.extend(["-r", self.rate_limit])
        
        cmd.append(url)
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {result.stderr}")
    
    def _find_output_file(self, expected_path: Path) -> Optional[Path]:
        """Find the actual output file (yt-dlp may modify extension)."""
        if expected_path.exists():
            return expected_path
        
        # Try common extensions
        for ext in ["mp4", "webm", "mkv", "m4a", "mp3"]:
            alt_path = expected_path.with_suffix(f".{ext}")
            if alt_path.exists():
                return alt_path
        
        return None
    
    def download_playlist(
        self,
        url: str,
        max_videos: Optional[int] = None,
    ) -> List[ScrapeResult]:
        """
        Download all videos from a playlist.
        
        Args:
            url: YouTube playlist URL
            max_videos: Maximum number of videos to download
            
        Returns:
            List of ScrapeResult objects
        """
        # Get playlist info
        if self._use_python_api:
            import yt_dlp
            
            with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
                info = ydl.extract_info(url, download=False)
        else:
            cmd = [
                self._ytdlp_path,
                "--flat-playlist",
                "--dump-json",
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"yt-dlp failed: {result.stderr}")
            
            # Parse multiple JSON objects
            entries = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    entries.append(json.loads(line))
            info = {"entries": entries}
        
        entries = info.get("entries", [])
        if max_videos:
            entries = entries[:max_videos]
        
        results = []
        for entry in entries:
            video_url = entry.get("url") or f"https://youtube.com/watch?v={entry.get('id')}"
            result = self.download(video_url)
            results.append(result)
        
        return results
    
    def search_and_download(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[ScrapeResult]:
        """
        Search YouTube and download matching videos.
        
        Args:
            query: Search query
            max_results: Maximum number of results to download
            
        Returns:
            List of ScrapeResult objects
        """
        search_url = f"ytsearch{max_results}:{query}"
        return self.download_playlist(search_url)


class VimeoScraper(YouTubeScraper):
    """
    Vimeo-optimized scraper using yt-dlp.
    
    Works similarly to YouTubeScraper but optimized for Vimeo URLs.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def can_handle(self, url: str) -> bool:
        return "vimeo.com" in url


class TwitterScraper(YouTubeScraper):
    """
    Twitter/X video scraper using yt-dlp.
    
    Extracts and downloads videos from tweets.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def can_handle(self, url: str) -> bool:
        return "twitter.com" in url or "x.com" in url


class TikTokScraper(YouTubeScraper):
    """
    TikTok video scraper using yt-dlp.
    
    Extracts and downloads TikTok videos.
    """
    
    def __init__(self, **kwargs):
        # TikTok videos are typically short-form
        kwargs.setdefault("quality", "best")
        kwargs.setdefault("format", "mp4")
        super().__init__(**kwargs)
    
    def can_handle(self, url: str) -> bool:
        return "tiktok.com" in url


# Auto-detection helper
def get_scraper_for_url(
    url: str,
    output_dir: Union[str, Path] = "./downloads",
    **kwargs,
) -> Union[YouTubeScraper, GenericScraper]:
    """
    Get the appropriate scraper for a URL.
    
    Args:
        url: URL to scrape
        output_dir: Output directory
        **kwargs: Additional arguments for the scraper
        
    Returns:
        Appropriate scraper instance
    """
    url_lower = url.lower()
    
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return YouTubeScraper(output_dir=output_dir, **kwargs)
    elif "vimeo.com" in url_lower:
        return VimeoScraper(output_dir=output_dir, **kwargs)
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return TwitterScraper(output_dir=output_dir, **kwargs)
    elif "tiktok.com" in url_lower:
        return TikTokScraper(output_dir=output_dir, **kwargs)
    else:
        return GenericScraper(output_dir=output_dir)

