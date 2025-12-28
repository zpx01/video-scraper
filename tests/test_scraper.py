"""Tests for the Scraper class."""

import pytest
import tempfile
from pathlib import Path


def test_scraper_initialization():
    """Test Scraper initialization."""
    from videoscraper import Scraper
    
    with tempfile.TemporaryDirectory() as tmpdir:
        scraper = Scraper(output_dir=tmpdir)
        assert Path(tmpdir).exists()


def test_scraper_with_config():
    """Test Scraper with custom config."""
    from videoscraper import Scraper, ScraperConfig
    
    config = ScraperConfig.conservative()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        scraper = Scraper(output_dir=tmpdir, config=config)
        assert scraper.config.rate_limit_per_second == 0.5


def test_scraper_with_filter():
    """Test Scraper with video filter."""
    from videoscraper import Scraper, VideoFilter
    
    filter = VideoFilter.hd()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        scraper = Scraper(output_dir=tmpdir, filter=filter)
        assert scraper.filter is not None
        assert scraper.filter.min_height == 720


def test_scrape_result_repr():
    """Test ScrapeResult representation."""
    from videoscraper.scraper import ScrapeResult
    
    result = ScrapeResult(
        url="https://example.com/video",
        success=True,
        output_path="/tmp/video.mp4",
    )
    
    repr_str = repr(result)
    assert "example.com" in repr_str
    assert "✓" in repr_str


def test_scrape_result_failed():
    """Test failed ScrapeResult."""
    from videoscraper.scraper import ScrapeResult
    
    result = ScrapeResult(
        url="https://example.com/video",
        success=False,
        error="Connection failed",
    )
    
    assert not result.success
    assert result.error == "Connection failed"
    assert "✗" in repr(result)


class TestAsyncScraper:
    """Tests for AsyncScraper."""
    
    @pytest.mark.asyncio
    async def test_async_scraper_initialization(self):
        """Test AsyncScraper initialization."""
        from videoscraper.scraper import AsyncScraper
        
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = AsyncScraper(output_dir=tmpdir)
            assert Path(tmpdir).exists()


class TestBatchScraper:
    """Tests for BatchScraper."""
    
    def test_batch_config_defaults(self):
        """Test BatchConfig default values."""
        from videoscraper.batch import BatchConfig
        
        config = BatchConfig()
        
        assert config.max_concurrent == 32
        assert config.max_per_domain == 4
        assert config.max_retries == 3
    
    def test_batch_scraper_add_urls(self):
        """Test adding URLs to BatchScraper."""
        from videoscraper.batch import BatchScraper, BatchConfig
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = BatchConfig(output_dir=tmpdir)
            scraper = BatchScraper(config)
            
            scraper.add_urls([
                "https://example.com/video1",
                "https://example.com/video2",
            ])
            
            # URLs should be queued
            assert len(scraper._urls) == 2
    
    def test_batch_scraper_add_from_text_file(self):
        """Test loading URLs from text file."""
        from videoscraper.batch import BatchScraper, BatchConfig
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create URL file
            url_file = Path(tmpdir) / "urls.txt"
            url_file.write_text(
                "https://example.com/video1\n"
                "https://example.com/video2\n"
                "# This is a comment\n"
                "https://example.com/video3\n"
            )
            
            config = BatchConfig(output_dir=tmpdir)
            scraper = BatchScraper(config)
            
            added = scraper.add_from_file(url_file)
            
            assert added == 3  # Comments should be ignored
    
    def test_batch_progress(self):
        """Test BatchProgress calculations."""
        from videoscraper.batch import BatchProgress
        
        progress = BatchProgress(
            total=100,
            completed=75,
            failed=5,
            in_progress=20,
            bytes_downloaded=1_000_000_000,  # 1GB
            elapsed_seconds=100,
        )
        
        assert progress.percent_complete == 75.0
        assert progress.success_rate == 93.75  # 75/(75+5)
        assert progress.download_speed_mbps == 10.0  # 1000MB/100s


class TestVideoFilter:
    """Tests for VideoFilter matching."""
    
    def test_filter_matches_format(self):
        """Test format matching."""
        from videoscraper import VideoFilter, VideoInfo
        
        filter = VideoFilter()
        filter.allowed_formats = ["mp4"]
        
        video_mp4 = VideoInfo(
            url="https://example.com/video.mp4",
            title="Test",
            description=None,
            duration_secs=None,
            width=None,
            height=None,
            format="mp4",
            file_size_bytes=None,
            thumbnail_url=None,
            source_page="https://example.com",
            quality=None,
            codec=None,
        )
        
        video_webm = VideoInfo(
            url="https://example.com/video.webm",
            title="Test",
            description=None,
            duration_secs=None,
            width=None,
            height=None,
            format="webm",
            file_size_bytes=None,
            thumbnail_url=None,
            source_page="https://example.com",
            quality=None,
            codec=None,
        )
        
        assert filter.matches(video_mp4)
        # Note: webm should not match when only mp4 is allowed

