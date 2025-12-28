"""
VideoScraper - High-performance video content scraping infrastructure

A Rust-powered library with Python bindings for large-scale video scraping.

Example:
    >>> from videoscraper import Pipeline, ScraperConfig
    >>> 
    >>> # Create a pipeline
    >>> pipeline = Pipeline()
    >>> 
    >>> # Add URLs to scrape
    >>> pipeline.add_urls([
    ...     "https://example.com/video1",
    ...     "https://example.com/video2",
    ... ])
    >>> 
    >>> # Run the pipeline
    >>> pipeline.run(concurrency=16)
    >>> 
    >>> # Check results
    >>> for job in pipeline.jobs():
    ...     print(f"{job.id}: {job.status}")
"""

from videoscraper._core import (
    # Configuration
    ScraperConfig,
    StorageConfig,
    
    # HTTP Client
    PyHttpClient as HttpClient,
    
    # Downloader
    PyDownloadManager as DownloadManager,
    DownloadProgress,
    DownloadResult,
    
    # Extractor
    PyVideoExtractor as VideoExtractor,
    VideoInfo,
    VideoFormat,
    ExtractionResult,
    
    # Storage
    PyStorage as Storage,
    ObjectMetadata,
    
    # Pipeline
    PyPipeline as Pipeline,
    ScrapeJob,
    JobStatus,
    PipelineStats,
    VideoFilter,
    
    # Convenience functions
    create_pipeline,
    extract_videos,
    download_file,
    
    # Version
    __version__,
)

# High-level API classes
from videoscraper.scraper import Scraper
from videoscraper.batch import BatchScraper
from videoscraper.sites import YouTubeScraper, GenericScraper

__all__ = [
    # Configuration
    "ScraperConfig",
    "StorageConfig",
    
    # Core components
    "HttpClient",
    "DownloadManager",
    "DownloadProgress",
    "DownloadResult",
    "VideoExtractor",
    "VideoInfo",
    "VideoFormat",
    "ExtractionResult",
    "Storage",
    "ObjectMetadata",
    
    # Pipeline
    "Pipeline",
    "ScrapeJob",
    "JobStatus",
    "PipelineStats",
    "VideoFilter",
    
    # High-level API
    "Scraper",
    "BatchScraper",
    "YouTubeScraper",
    "GenericScraper",
    
    # Functions
    "create_pipeline",
    "extract_videos",
    "download_file",
    
    # Version
    "__version__",
]

