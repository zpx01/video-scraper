"""
Command-line interface for VideoScraper.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="videoscraper",
        description="High-performance video content scraping",
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Download command
    download_parser = subparsers.add_parser(
        "download",
        help="Download video(s) from URL(s)",
    )
    download_parser.add_argument(
        "urls",
        nargs="+",
        help="URL(s) to download",
    )
    download_parser.add_argument(
        "-o", "--output",
        default="./downloads",
        help="Output directory (default: ./downloads)",
    )
    download_parser.add_argument(
        "-q", "--quality",
        default="best",
        help="Video quality (best, 1080p, 720p, etc.)",
    )
    download_parser.add_argument(
        "-f", "--format",
        default="mp4",
        help="Output format (mp4, webm, mkv)",
    )
    download_parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=8,
        help="Number of concurrent downloads",
    )
    download_parser.add_argument(
        "--cookies",
        help="Path to cookies file",
    )
    download_parser.add_argument(
        "-r", "--rate-limit",
        help="Rate limit (e.g., 50M for 50 MB/s)",
    )
    download_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    
    # Extract command
    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract video URLs from a page (no download)",
    )
    extract_parser.add_argument(
        "url",
        help="URL to extract from",
    )
    extract_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    
    # Batch command
    batch_parser = subparsers.add_parser(
        "batch",
        help="Batch download from URL list file",
    )
    batch_parser.add_argument(
        "file",
        help="File containing URLs (txt, csv, or json)",
    )
    batch_parser.add_argument(
        "-o", "--output",
        default="./downloads",
        help="Output directory",
    )
    batch_parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=32,
        help="Number of concurrent downloads",
    )
    batch_parser.add_argument(
        "--checkpoint",
        help="Checkpoint file for resume",
    )
    batch_parser.add_argument(
        "--results",
        help="Output results to file (csv or json)",
    )
    batch_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    
    # Info command
    info_parser = subparsers.add_parser(
        "info",
        help="Get video information",
    )
    info_parser.add_argument(
        "url",
        help="Video URL",
    )
    info_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    
    parsed = parser.parse_args(args)
    
    if parsed.command is None:
        parser.print_help()
        return 1
    
    try:
        if parsed.command == "download":
            return cmd_download(parsed)
        elif parsed.command == "extract":
            return cmd_extract(parsed)
        elif parsed.command == "batch":
            return cmd_batch(parsed)
        elif parsed.command == "info":
            return cmd_info(parsed)
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Error: {e}")
        if hasattr(parsed, "verbose") and parsed.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_download(args: argparse.Namespace) -> int:
    """Handle download command."""
    from videoscraper.sites import get_scraper_for_url
    from videoscraper.scraper import Scraper
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    success_count = 0
    fail_count = 0
    
    for url in args.urls:
        logger.info(f"Downloading: {url}")
        
        try:
            scraper = get_scraper_for_url(
                url,
                output_dir=output_dir,
                quality=args.quality,
                format=args.format,
                cookies_file=args.cookies,
                rate_limit=args.rate_limit,
            )
            
            result = scraper.download(url) if hasattr(scraper, 'download') else scraper.scrape(url)
            
            if result.success:
                logger.info(f"✓ Downloaded: {result.output_path}")
                success_count += 1
            else:
                logger.error(f"✗ Failed: {result.error}")
                fail_count += 1
                
        except Exception as e:
            logger.error(f"✗ Error: {e}")
            fail_count += 1
    
    logger.info(f"Complete: {success_count} succeeded, {fail_count} failed")
    return 0 if fail_count == 0 else 1


def cmd_extract(args: argparse.Namespace) -> int:
    """Handle extract command."""
    from videoscraper import extract_videos
    
    logger.info(f"Extracting videos from: {args.url}")
    
    videos = extract_videos(args.url)
    
    if args.json:
        output = [
            {
                "url": v.url,
                "title": v.title,
                "format": v.format,
                "quality": v.quality,
                "size_bytes": v.file_size_bytes,
            }
            for v in videos
        ]
        print(json.dumps(output, indent=2))
    else:
        if not videos:
            logger.info("No videos found")
        else:
            logger.info(f"Found {len(videos)} video(s):")
            for i, v in enumerate(videos, 1):
                print(f"  {i}. {v.url}")
                if v.title:
                    print(f"     Title: {v.title}")
                if v.format:
                    print(f"     Format: {v.format}")
    
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    """Handle batch command."""
    from videoscraper.batch import BatchScraper, BatchConfig
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    config = BatchConfig(
        max_concurrent=args.concurrency,
        output_dir=args.output,
        checkpoint_file=args.checkpoint,
        verbose=args.verbose,
    )
    
    scraper = BatchScraper(config)
    
    # Load URLs
    file_path = Path(args.file)
    if not file_path.exists():
        logger.error(f"File not found: {args.file}")
        return 1
    
    added = scraper.add_from_file(file_path)
    logger.info(f"Loaded {added} URLs")
    
    # Run batch
    results = scraper.run()
    
    # Summary
    progress = scraper.progress()
    logger.info(
        f"Complete: {progress.completed} succeeded, "
        f"{progress.failed} failed, "
        f"{progress.bytes_downloaded / 1_000_000:.1f} MB downloaded"
    )
    
    # Export results
    if args.results:
        scraper.export_results(args.results)
        logger.info(f"Results exported to: {args.results}")
    
    return 0 if progress.failed == 0 else 1


def cmd_info(args: argparse.Namespace) -> int:
    """Handle info command."""
    from videoscraper.sites import get_scraper_for_url
    
    url = args.url
    
    # For YouTube-like sites, use site-specific scraper
    if any(s in url.lower() for s in ["youtube.com", "youtu.be", "vimeo.com"]):
        scraper = get_scraper_for_url(url)
        if hasattr(scraper, "get_info"):
            info = scraper.get_info(url)
            
            if args.json:
                print(json.dumps(info.to_dict(), indent=2))
            else:
                print(f"Title: {info.title}")
                print(f"ID: {info.id}")
                if info.duration:
                    mins, secs = divmod(info.duration, 60)
                    print(f"Duration: {mins}:{secs:02d}")
                if info.uploader:
                    print(f"Uploader: {info.uploader}")
                if info.view_count:
                    print(f"Views: {info.view_count:,}")
                if info.formats:
                    print(f"Available formats: {len(info.formats)}")
                    for f in info.formats[:5]:
                        dims = f"{f.get('width', '?')}x{f.get('height', '?')}"
                        print(f"  - {f.get('format_id')}: {f.get('ext')} {dims}")
            
            return 0
    
    # For generic sites, use extraction
    from videoscraper import extract_videos
    
    videos = extract_videos(url)
    
    if args.json:
        output = [{"url": v.url, "title": v.title, "format": v.format} for v in videos]
        print(json.dumps(output, indent=2))
    else:
        if not videos:
            print("No videos found")
        else:
            print(f"Found {len(videos)} video(s):")
            for v in videos:
                print(f"  - {v.url}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

