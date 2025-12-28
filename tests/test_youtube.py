#!/usr/bin/env python3
"""
Test script for VideoScraper - YouTube downloads.

This script tests the scraper on a few YouTube videos.

Requirements:
    pip install yt-dlp

Usage:
    python test_youtube.py
"""

import os
import sys
from pathlib import Path

# Test URLs
TEST_VIDEOS = [
    "https://www.youtube.com/watch?v=XALBGkjkUPQ",
    "https://www.youtube.com/watch?v=Lw9ylpT806U",
    "https://www.youtube.com/watch?v=3iH8l6dN6Ow",
]

def main():
    print("=" * 60)
    print("VideoScraper - YouTube Test")
    print("=" * 60)
    
    # Check yt-dlp is installed
    try:
        import yt_dlp
        print(f"✓ yt-dlp version: {yt_dlp.version.__version__}")
    except ImportError:
        print("✗ yt-dlp not installed. Installing...")
        os.system(f"{sys.executable} -m pip install yt-dlp")
        import yt_dlp
    
    # Import the scraper
    try:
        from videoscraper import YouTubeScraper
        print("✓ VideoScraper imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import VideoScraper: {e}")
        print("  Make sure you've built it with: maturin develop --release")
        return 1
    
    # Create output directory
    output_dir = Path("./test_downloads")
    output_dir.mkdir(exist_ok=True)
    print(f"✓ Output directory: {output_dir.absolute()}")
    
    # Create scraper
    scraper = YouTubeScraper(
        output_dir=str(output_dir),
        quality="720p",  # Use 720p for faster testing
        format="mp4",
    )
    print("✓ YouTubeScraper created")
    print()
    
    results = []
    
    for i, url in enumerate(TEST_VIDEOS, 1):
        print(f"[{i}/{len(TEST_VIDEOS)}] Processing: {url}")
        print("-" * 50)
        
        try:
            # Get video info first
            print("  📋 Getting video info...")
            info = scraper.get_info(url)
            print(f"  Title: {info.title}")
            print(f"  Duration: {info.duration or 'N/A'} seconds")
            print(f"  Uploader: {info.uploader or 'N/A'}")
            
            # Download the video
            print("  ⬇️ Downloading...")
            result = scraper.download(url)
            
            if result.success:
                file_size = os.path.getsize(result.output_path) if result.output_path else 0
                size_mb = file_size / (1024 * 1024)
                print(f"  ✓ Downloaded: {result.output_path}")
                print(f"  ✓ Size: {size_mb:.1f} MB")
                results.append(("success", url, result.output_path))
            else:
                print(f"  ✗ Failed: {result.error}")
                results.append(("failed", url, result.error))
                
        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append(("error", url, str(e)))
        
        print()
    
    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    
    success = sum(1 for r in results if r[0] == "success")
    failed = len(results) - success
    
    print(f"Total: {len(results)} videos")
    print(f"Success: {success}")
    print(f"Failed: {failed}")
    print()
    
    for status, url, detail in results:
        icon = "✓" if status == "success" else "✗"
        print(f"  {icon} {url}")
        if status == "success":
            print(f"    → {detail}")
        else:
            print(f"    → Error: {detail}")
    
    print()
    print(f"Downloads saved to: {output_dir.absolute()}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

