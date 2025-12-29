#!/usr/bin/env python3
"""
VideoScraper Local Verification Demo
=====================================

This script verifies that VideoScraper is working correctly on your local machine
before deploying to GCP. It tests:

1. Core Rust bindings
2. Video extraction from web pages
3. Download functionality
4. YouTube support (if yt-dlp installed)
5. Pipeline orchestration
6. Performance metrics

Run this before deploying to GCP to ensure everything works.

Usage:
    python demo/local_verification.py
"""

import os
import sys
import time
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple, Optional

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration_ms: float
    message: str
    details: Optional[str] = None


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str):
    """Print a styled header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}  {text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")


def print_test_result(result: TestResult):
    """Print a test result with styling."""
    status = f"{Colors.GREEN}✓ PASS{Colors.END}" if result.passed else f"{Colors.RED}✗ FAIL{Colors.END}"
    print(f"  {status} {result.name} ({result.duration_ms:.0f}ms)")
    if result.message:
        print(f"       {Colors.CYAN}{result.message}{Colors.END}")
    if result.details and not result.passed:
        print(f"       {Colors.YELLOW}{result.details}{Colors.END}")


def run_test(name: str, test_func) -> TestResult:
    """Run a test function and capture the result."""
    start = time.time()
    try:
        message = test_func()
        duration_ms = (time.time() - start) * 1000
        return TestResult(name=name, passed=True, duration_ms=duration_ms, message=message or "OK")
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        return TestResult(
            name=name,
            passed=False,
            duration_ms=duration_ms,
            message=str(e),
            details=str(type(e).__name__)
        )


# ============================================================================
# Test Functions
# ============================================================================

def test_import_core():
    """Test that the Rust core module can be imported."""
    from videoscraper._core import __version__
    return f"Version: {__version__}"


def test_scraper_config():
    """Test ScraperConfig creation and presets."""
    from videoscraper import ScraperConfig
    
    # Default config
    config = ScraperConfig()
    assert config.max_concurrent_downloads == 32
    assert config.enable_resume == True
    
    # High performance preset
    hp_config = ScraperConfig.high_performance()
    assert hp_config.max_concurrent_downloads == 128
    assert hp_config.rate_limit_per_second == 50.0
    
    # Conservative preset
    con_config = ScraperConfig.conservative()
    assert con_config.rate_limit_per_second == 0.5
    
    return f"Default: {config.max_concurrent_downloads} concurrent, HP: {hp_config.max_concurrent_downloads}"


def test_storage_config():
    """Test StorageConfig creation."""
    from videoscraper import StorageConfig
    
    # Local storage
    local = StorageConfig.local("/tmp/videos")
    assert local.backend == "local"
    
    # S3 config
    s3 = StorageConfig.s3("my-bucket", region="us-west-2")
    assert s3.backend == "s3"
    
    # GCS config
    gcs = StorageConfig.gcs("my-bucket", project="my-project")
    assert gcs.backend == "gcs"
    
    return "Local, S3, and GCS configs created successfully"


def test_http_client():
    """Test HTTP client functionality."""
    from videoscraper import HttpClient, ScraperConfig
    
    config = ScraperConfig()
    client = HttpClient(config)
    
    # Test a simple GET request
    text = client.get_text("https://httpbin.org/html")
    assert "Herman Melville" in text
    
    return "HTTP GET successful"


def test_video_extractor():
    """Test video URL extraction from HTML."""
    from videoscraper import VideoExtractor, ScraperConfig
    
    config = ScraperConfig()
    extractor = VideoExtractor(config)
    
    # Test HTML parsing
    html = '''
    <html>
    <head><title>Test Video Page</title></head>
    <body>
        <video src="https://example.com/video.mp4"></video>
        <video>
            <source src="https://example.com/video2.webm" type="video/webm">
        </video>
    </body>
    </html>
    '''
    
    videos = extractor.extract_from_html(html, "https://example.com")
    assert len(videos) >= 1
    
    return f"Extracted {len(videos)} video(s) from HTML"


def test_video_filter():
    """Test VideoFilter functionality."""
    from videoscraper import VideoFilter
    
    # HD filter
    hd_filter = VideoFilter.hd()
    assert hd_filter.min_height == 720
    assert "mp4" in hd_filter.allowed_formats
    
    # UHD filter
    uhd_filter = VideoFilter.uhd()
    assert uhd_filter.min_height == 2160
    
    # Custom filter
    custom = VideoFilter()
    custom.min_height = 480
    custom.max_height = 1080
    custom.allowed_formats = ["mp4"]
    
    return "HD, UHD, and custom filters created"


def test_pipeline_creation():
    """Test Pipeline creation and basic operations."""
    from videoscraper import Pipeline, ScraperConfig, StorageConfig
    
    config = ScraperConfig()
    storage = StorageConfig.local("/tmp/test_pipeline")
    
    pipeline = Pipeline(config, storage)
    
    # Check initial stats
    stats = pipeline.stats()
    assert stats.total_jobs == 0
    
    return "Pipeline created successfully"


def test_downloader():
    """Test download manager with a small file."""
    from videoscraper import DownloadManager, ScraperConfig
    import tempfile
    
    config = ScraperConfig()
    manager = DownloadManager(config)
    
    # Download a small test file
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = f"{tmpdir}/test.txt"
        
        # Use httpbin to download a small response
        result = manager.download(
            "https://httpbin.org/bytes/1024",  # 1KB
            output_path
        )
        
        assert result.size_bytes == 1024
        assert os.path.exists(output_path)
    
    return f"Downloaded {result.size_bytes} bytes @ {result.avg_speed_bytes_per_sec/1024:.1f} KB/s"


def test_scraper_class():
    """Test the high-level Scraper class."""
    from videoscraper import Scraper
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        scraper = Scraper(output_dir=tmpdir)
        
        # Just test initialization - actual scraping would need valid URLs
        assert scraper.output_dir.exists()
        assert scraper.config is not None
    
    return "Scraper initialized successfully"


def test_youtube_available():
    """Check if yt-dlp is available for YouTube support."""
    try:
        import yt_dlp
        return f"yt-dlp version: {yt_dlp.version.__version__}"
    except ImportError:
        return "yt-dlp not installed (optional for YouTube)"


def test_youtube_scraper():
    """Test YouTubeScraper initialization."""
    from videoscraper.sites import YouTubeScraper
    import tempfile
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = YouTubeScraper(
                output_dir=tmpdir,
                quality="720p",
                format="mp4",
            )
            return "YouTubeScraper initialized successfully"
    except RuntimeError as e:
        if "yt-dlp" in str(e):
            return "Skipped (yt-dlp not installed)"
        raise


def test_batch_scraper():
    """Test BatchScraper configuration."""
    from videoscraper.batch import BatchScraper, BatchConfig
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config = BatchConfig(
            max_concurrent=32,
            output_dir=tmpdir,
        )
        
        scraper = BatchScraper(config)
        
        # Add some test URLs
        scraper.add_urls([
            "https://example.com/video1",
            "https://example.com/video2",
        ])
        
        assert len(scraper._urls) == 2
    
    return "BatchScraper with 32 concurrent workers"


def test_proxy_config():
    """Test proxy configuration classes."""
    from videoscraper.proxy import ProxyConfig, ProxyRotator
    
    # Test Bright Data config
    config = ProxyConfig.brightdata(
        username="test_user",
        password="test_pass",
        country="us",
    )
    
    assert config.provider == "brightdata"
    assert config.country == "us"
    
    # Test rotator
    rotator = ProxyRotator(config)
    proxy_url = rotator.get_proxy()
    
    assert "test_user" in proxy_url
    assert "brd.superproxy.io" in proxy_url
    
    return "Bright Data proxy configured"


def test_concurrent_performance():
    """Test concurrent download performance."""
    from videoscraper import DownloadManager, ScraperConfig
    import tempfile
    
    config = ScraperConfig.high_performance()
    manager = DownloadManager(config)
    
    # Download multiple small files concurrently
    urls = [(f"https://httpbin.org/bytes/{512}", f"file_{i}.bin") for i in range(5)]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        items = [(url, f"{tmpdir}/{fname}") for url, fname in urls]
        
        start = time.time()
        results = manager.download_batch(items)
        duration = time.time() - start
        
        total_bytes = sum(r.size_bytes for r in results)
        throughput = total_bytes / duration / 1024
        
        return f"5 files, {total_bytes} bytes, {throughput:.1f} KB/s"


def test_json_serialization():
    """Test config serialization to JSON."""
    from videoscraper import ScraperConfig
    
    config = ScraperConfig()
    json_str = config.to_json()
    
    # Parse back
    restored = ScraperConfig.from_json(json_str)
    
    assert restored.max_concurrent_downloads == config.max_concurrent_downloads
    assert restored.enable_resume == config.enable_resume
    
    return f"Config serializes to {len(json_str)} bytes of JSON"


# ============================================================================
# Main Runner
# ============================================================================

def run_all_tests() -> Tuple[List[TestResult], int, int]:
    """Run all verification tests."""
    
    tests = [
        ("Import Core Module", test_import_core),
        ("ScraperConfig", test_scraper_config),
        ("StorageConfig", test_storage_config),
        ("HTTP Client", test_http_client),
        ("Video Extractor", test_video_extractor),
        ("Video Filter", test_video_filter),
        ("Pipeline Creation", test_pipeline_creation),
        ("Download Manager", test_downloader),
        ("Scraper Class", test_scraper_class),
        ("YouTube Support Check", test_youtube_available),
        ("YouTube Scraper", test_youtube_scraper),
        ("Batch Scraper", test_batch_scraper),
        ("Proxy Configuration", test_proxy_config),
        ("Concurrent Downloads", test_concurrent_performance),
        ("JSON Serialization", test_json_serialization),
    ]
    
    results = []
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        result = run_test(name, test_func)
        results.append(result)
        print_test_result(result)
        
        if result.passed:
            passed += 1
        else:
            failed += 1
    
    return results, passed, failed


def main():
    """Main entry point."""
    print_header("VideoScraper Local Verification")
    
    print(f"{Colors.CYAN}Running verification tests...{Colors.END}\n")
    
    results, passed, failed = run_all_tests()
    
    # Summary
    print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}  Summary{Colors.END}")
    print(f"{Colors.BOLD}{'='*60}{Colors.END}\n")
    
    total = passed + failed
    pass_rate = (passed / total * 100) if total > 0 else 0
    
    print(f"  Total Tests: {total}")
    print(f"  {Colors.GREEN}Passed: {passed}{Colors.END}")
    print(f"  {Colors.RED}Failed: {failed}{Colors.END}")
    print(f"  Pass Rate: {pass_rate:.1f}%")
    
    if failed == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✓ All tests passed! VideoScraper is ready.{Colors.END}")
        print(f"\n{Colors.CYAN}Next steps:{Colors.END}")
        print("  1. Run the performance demo: python demo/performance_demo.py")
        print("  2. Deploy to GCP: cd deploy/gcp && ./deploy.sh")
        print("  3. Read the full guide: demo/GCP_DEMO_GUIDE.md")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ Some tests failed. Please fix issues before deploying.{Colors.END}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

