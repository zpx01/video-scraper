"""Tests for configuration classes."""

import pytest


def test_scraper_config_default():
    """Test default ScraperConfig values."""
    from videoscraper import ScraperConfig
    
    config = ScraperConfig()
    
    assert config.max_concurrent_downloads == 32
    assert config.max_requests_per_domain == 8
    assert config.enable_resume is True
    assert config.max_retries == 5
    assert config.rate_limit_per_second == 2.0


def test_scraper_config_high_performance():
    """Test high performance preset."""
    from videoscraper import ScraperConfig
    
    config = ScraperConfig.high_performance()
    
    assert config.max_concurrent_downloads == 128
    assert config.rate_limit_per_second == 50.0
    assert config.respect_robots_txt is False


def test_scraper_config_conservative():
    """Test conservative preset."""
    from videoscraper import ScraperConfig
    
    config = ScraperConfig.conservative()
    
    assert config.max_concurrent_downloads == 4
    assert config.rate_limit_per_second == 0.5
    assert config.respect_robots_txt is True


def test_scraper_config_serialization():
    """Test JSON serialization."""
    from videoscraper import ScraperConfig
    
    config = ScraperConfig()
    config.max_concurrent_downloads = 100
    
    json_str = config.to_json()
    assert "max_concurrent_downloads" in json_str
    assert "100" in json_str
    
    loaded = ScraperConfig.from_json(json_str)
    assert loaded.max_concurrent_downloads == 100


def test_storage_config_local():
    """Test local storage configuration."""
    from videoscraper import StorageConfig
    
    config = StorageConfig.local("/tmp/videos")
    
    assert config.backend == "local"
    assert config.local_path == "/tmp/videos"


def test_storage_config_s3():
    """Test S3 storage configuration."""
    from videoscraper import StorageConfig
    
    config = StorageConfig.s3(
        bucket="my-bucket",
        region="us-west-2",
        endpoint=None,
        key_prefix="videos/",
    )
    
    assert config.backend == "s3"
    assert config.s3_bucket == "my-bucket"
    assert config.s3_region == "us-west-2"
    assert config.key_prefix == "videos/"


def test_storage_config_gcs():
    """Test GCS storage configuration."""
    from videoscraper import StorageConfig
    
    config = StorageConfig.gcs(
        bucket="my-gcs-bucket",
        project="my-project",
    )
    
    assert config.backend == "gcs"
    assert config.gcs_bucket == "my-gcs-bucket"
    assert config.gcs_project == "my-project"


def test_video_filter_default():
    """Test default VideoFilter."""
    from videoscraper import VideoFilter
    
    filter = VideoFilter()
    
    assert filter.min_width is None
    assert filter.min_height is None
    assert filter.allowed_formats == []


def test_video_filter_hd():
    """Test HD filter preset."""
    from videoscraper import VideoFilter
    
    filter = VideoFilter.hd()
    
    assert filter.min_height == 720
    assert "mp4" in filter.allowed_formats
    assert "1080p" in filter.quality_preference


def test_video_filter_uhd():
    """Test UHD filter preset."""
    from videoscraper import VideoFilter
    
    filter = VideoFilter.uhd()
    
    assert filter.min_height == 2160
    assert "2160p" in filter.quality_preference

