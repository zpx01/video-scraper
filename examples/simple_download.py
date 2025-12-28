#!/usr/bin/env python3
"""
Simple video download example.

This example shows the basic usage of VideoScraper for downloading
videos from web pages.
"""

from videoscraper import Scraper, VideoFilter


def main():
    # Create a scraper with default settings
    scraper = Scraper(output_dir="./downloads")
    
    # Download a single video
    result = scraper.scrape("https://example.com/video-page.html")
    
    if result.success:
        print(f"✓ Downloaded: {result.output_path}")
        if result.download_result:
            print(f"  Size: {result.download_result.size_bytes / 1_000_000:.1f} MB")
            print(f"  Speed: {result.download_result.avg_speed_bytes_per_sec / 1_000_000:.1f} MB/s")
    else:
        print(f"✗ Failed: {result.error}")
    
    # Download with quality filter
    scraper_hd = Scraper(
        output_dir="./downloads",
        filter=VideoFilter.hd(),  # Only 720p+
    )
    
    result = scraper_hd.scrape("https://example.com/another-video.html")
    print(f"HD download: {'success' if result.success else 'failed'}")


if __name__ == "__main__":
    main()

