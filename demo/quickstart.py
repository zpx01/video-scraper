#!/usr/bin/env python3
"""
VideoScraper Quickstart Demo
============================

A simple demonstration of VideoScraper's core features.
Perfect for first-time users and GitHub README examples.

This script shows:
1. Basic scraping from a web page
2. YouTube downloading (if yt-dlp installed)
3. Batch processing
4. Performance metrics

Usage:
    python demo/quickstart.py

Requirements:
    pip install videoscraper yt-dlp  # Optional: yt-dlp for YouTube
"""

import os
import sys
import time
import tempfile
from pathlib import Path

# Add project to path (for development)
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


def main():
    print("🎬 VideoScraper Quickstart Demo")
    print("=" * 50)
    
    # Import VideoScraper
    try:
        from videoscraper import (
            Scraper,
            ScraperConfig,
            VideoFilter,
            __version__
        )
        print(f"\n✓ VideoScraper v{__version__} loaded")
    except ImportError as e:
        print(f"\n✗ Import failed: {e}")
        print("\nInstall VideoScraper first:")
        print("  cd video-scraper && make dev")
        return 1
    
    # Create temporary output directory
    output_dir = tempfile.mkdtemp(prefix="videoscraper_demo_")
    print(f"✓ Output directory: {output_dir}")
    
    # ========================================
    # Example 1: Basic Scraping
    # ========================================
    print("\n" + "-" * 50)
    print("📥 Example 1: Basic Video Extraction")
    print("-" * 50)
    
    # Create a scraper
    scraper = Scraper(output_dir=output_dir)
    
    # Demo HTML parsing (without network request)
    from videoscraper import VideoExtractor
    
    extractor = VideoExtractor()
    demo_html = '''
    <html>
    <head><title>Demo Video Page</title></head>
    <body>
        <video src="https://example.com/video.mp4" poster="thumb.jpg"></video>
        <video>
            <source src="https://example.com/hd_video.webm" type="video/webm">
            <source src="https://example.com/sd_video.mp4" type="video/mp4">
        </video>
        <a href="https://cdn.example.com/download.mp4">Download Video</a>
    </body>
    </html>
    '''
    
    videos = extractor.extract_from_html(demo_html, "https://example.com")
    print(f"✓ Found {len(videos)} video(s) in HTML")
    
    for i, video in enumerate(videos[:3]):
        print(f"  [{i+1}] {video.url[:50]}...")
        if video.format:
            print(f"      Format: {video.format}")
    
    # ========================================
    # Example 2: YouTube Download
    # ========================================
    print("\n" + "-" * 50)
    print("🎥 Example 2: YouTube Download")
    print("-" * 50)
    
    try:
        # First check if yt-dlp is available
        import yt_dlp
        print(f"✓ yt-dlp version: {yt_dlp.version.__version__}")
        
        from videoscraper.sites import YouTubeScraper
        
        yt_scraper = YouTubeScraper(
            output_dir=output_dir,
            quality="360p",  # Low quality for quick demo
            format="mp4",
        )
        
        # Get video info without downloading
        print("Fetching video info...")
        # Use a very reliable, always-available video
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        
        info = yt_scraper.get_info(test_url)
        print(f"✓ Video: {info.title[:50]}...")
        print(f"  Duration: {info.duration}s")
        print(f"  Channel: {info.channel}")
        print(f"  Available formats: {len(info.formats or [])}")
        
        # Download (optional - uncomment to actually download)
        # print("\nDownloading...")
        # result = yt_scraper.download(test_url)
        # if result.success:
        #     print(f"✓ Downloaded: {result.output_path}")
        
    except ImportError:
        print("⚠ yt-dlp not installed - YouTube demo skipped")
        print("  Install with: pip install yt-dlp")
    except Exception as e:
        print(f"⚠ YouTube example error: {e}")
    
    # ========================================
    # Example 3: Batch Processing
    # ========================================
    print("\n" + "-" * 50)
    print("📦 Example 3: Batch Processing")
    print("-" * 50)
    
    try:
        from videoscraper.batch import BatchScraper, BatchConfig
        
        config = BatchConfig(
            max_concurrent=16,
            output_dir=output_dir,
        )
        
        batch = BatchScraper(config)
        
        # Add URLs (these are just for demonstration)
        batch.add_urls([
            "https://example.com/video1.html",
            "https://example.com/video2.html",
            "https://example.com/video3.html",
        ])
        
        print(f"✓ Added {len(batch._urls)} URLs to batch queue")
        print("  To process: batch.run()")
        
    except Exception as e:
        print(f"⚠ Batch example skipped: {e}")
    
    # ========================================
    # Example 4: Configuration Options
    # ========================================
    print("\n" + "-" * 50)
    print("⚙️  Example 4: Configuration")
    print("-" * 50)
    
    # Default config
    config = ScraperConfig()
    print(f"Default concurrency: {config.max_concurrent_downloads}")
    print(f"Rate limit: {config.rate_limit_per_second} req/s")
    
    # High-performance preset
    hp_config = ScraperConfig.high_performance()
    print(f"\nHigh-performance concurrency: {hp_config.max_concurrent_downloads}")
    print(f"High-performance rate limit: {hp_config.rate_limit_per_second} req/s")
    
    # Custom filter
    filter = VideoFilter.hd()
    print(f"\nHD filter: ≥{filter.min_height}p, formats: {filter.allowed_formats}")
    
    # ========================================
    # Example 5: Pipeline API
    # ========================================
    print("\n" + "-" * 50)
    print("🔄 Example 5: Pipeline API")
    print("-" * 50)
    
    try:
        from videoscraper import Pipeline, StorageConfig
        
        storage = StorageConfig.local(output_dir)
        pipeline = Pipeline(config, storage)
        
        stats = pipeline.stats()
        print(f"✓ Pipeline created")
        print(f"  Total jobs: {stats.total_jobs}")
        print(f"  Active: {stats.active_jobs}")
        
    except Exception as e:
        print(f"⚠ Pipeline example skipped: {e}")
    
    # ========================================
    # Summary
    # ========================================
    print("\n" + "=" * 50)
    print("✅ Quickstart Demo Complete!")
    print("=" * 50)
    
    print("\n📚 Next Steps:")
    print("  1. Read the full documentation: README.md")
    print("  2. Run the verification: python demo/local_verification.py")
    print("  3. Run performance tests: python demo/performance_demo.py")
    print("  4. Deploy to GCP: demo/GCP_DEMO_GUIDE.md")
    
    print(f"\n📁 Demo files were written to: {output_dir}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

