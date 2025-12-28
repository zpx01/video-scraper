#!/usr/bin/env python3
"""
YouTube scraping example.

This example shows how to use the YouTubeScraper for downloading
YouTube videos, playlists, and channels.

Requires: pip install yt-dlp
"""

from videoscraper import YouTubeScraper


def download_single_video():
    """Download a single YouTube video."""
    scraper = YouTubeScraper(
        output_dir="./youtube_videos",
        quality="1080p",
        format="mp4",
    )
    
    # Replace with actual video URL
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    # Get video info first (no download)
    info = scraper.get_info(video_url)
    print(f"Title: {info.title}")
    print(f"Duration: {info.duration} seconds")
    print(f"Views: {info.view_count:,}")
    print(f"Available formats: {len(info.formats or [])}")
    
    # Download the video
    result = scraper.download(video_url)
    
    if result.success:
        print(f"✓ Downloaded: {result.output_path}")
    else:
        print(f"✗ Failed: {result.error}")


def download_playlist():
    """Download videos from a YouTube playlist."""
    scraper = YouTubeScraper(
        output_dir="./youtube_playlists",
        quality="720p",
        format="mp4",
    )
    
    # Replace with actual playlist URL
    playlist_url = "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    
    # Download first 5 videos from playlist
    results = scraper.download_playlist(playlist_url, max_videos=5)
    
    success = sum(1 for r in results if r.success)
    failed = len(results) - success
    
    print(f"Playlist download complete: {success} succeeded, {failed} failed")


def download_with_authentication():
    """Download age-restricted or private videos with cookies."""
    scraper = YouTubeScraper(
        output_dir="./youtube_auth",
        quality="best",
        cookies_file="./cookies.txt",  # Export from browser
    )
    
    # This can download age-restricted or subscriber-only content
    result = scraper.download("https://www.youtube.com/watch?v=PRIVATE_VIDEO_ID")
    print(f"Authenticated download: {'success' if result.success else 'failed'}")


def download_audio_only():
    """Extract audio from YouTube videos."""
    scraper = YouTubeScraper(
        output_dir="./youtube_audio",
        extract_audio=True,
    )
    
    result = scraper.download("https://www.youtube.com/watch?v=VIDEO_ID")
    
    if result.success:
        print(f"✓ Audio extracted: {result.output_path}")


def search_and_download():
    """Search YouTube and download results."""
    scraper = YouTubeScraper(
        output_dir="./youtube_search",
        quality="720p",
    )
    
    # Search for videos and download top 3 results
    results = scraper.search_and_download("python tutorial", max_results=3)
    
    for result in results:
        status = "✓" if result.success else "✗"
        print(f"{status} {result.url}")


if __name__ == "__main__":
    print("=== Single Video ===")
    download_single_video()
    
    print("\n=== Playlist ===")
    download_playlist()
    
    print("\n=== Audio Only ===")
    download_audio_only()
    
    print("\n=== Search ===")
    search_and_download()

