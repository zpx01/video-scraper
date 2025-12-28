#!/usr/bin/env python3
"""
Batch scraping example for large-scale video collection.

This example shows how to use BatchScraper for processing thousands
or millions of URLs with checkpointing and progress tracking.
"""

import logging
from videoscraper import BatchScraper, BatchConfig, VideoFilter
from videoscraper.batch import BatchProgress

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def on_progress(progress: BatchProgress):
    """Callback for progress updates."""
    print(
        f"Progress: {progress.completed}/{progress.total} "
        f"({progress.percent_complete:.1f}%) - "
        f"{progress.download_speed_mbps:.1f} MB/s"
    )


def on_complete(result):
    """Callback when a download completes."""
    print(f"✓ {result.output_path}")


def on_error(url: str, error: Exception):
    """Callback when a download fails."""
    print(f"✗ {url}: {error}")


def main():
    # Configure batch scraping
    config = BatchConfig(
        # Concurrency
        max_concurrent=64,
        max_per_domain=4,
        
        # Output
        output_dir="./batch_downloads",
        organize_by_domain=True,
        
        # Checkpointing for resume
        checkpoint_file="./batch_checkpoint.json",
        checkpoint_interval=50,
        
        # Rate limiting
        requests_per_second=10.0,
        
        # Retries
        max_retries=3,
        retry_delay_seconds=5.0,
        
        # Filtering (optional)
        video_filter=VideoFilter.hd(),
        
        # Callbacks
        on_progress=on_progress,
        on_complete=on_complete,
        on_error=on_error,
        
        # Logging
        log_file="./batch_scraping.log",
        verbose=True,
    )
    
    # Create scraper
    scraper = BatchScraper(config)
    
    # Add URLs from file
    # Supports: .txt (one URL per line), .csv, .json
    # scraper.add_from_file("urls.txt")
    
    # Or add URLs directly
    urls = [
        "https://example.com/video1",
        "https://example.com/video2",
        "https://example.com/video3",
        # ... add thousands more
    ]
    scraper.add_urls(urls)
    
    print(f"Starting batch scrape of {len(urls)} URLs...")
    
    # Run the batch
    results = scraper.run()
    
    # Get final statistics
    progress = scraper.progress()
    print("\n=== Final Statistics ===")
    print(f"Total: {progress.total}")
    print(f"Completed: {progress.completed}")
    print(f"Failed: {progress.failed}")
    print(f"Success rate: {progress.success_rate:.1f}%")
    print(f"Total downloaded: {progress.bytes_downloaded / 1_000_000_000:.2f} GB")
    print(f"Average speed: {progress.download_speed_mbps:.1f} MB/s")
    print(f"Elapsed time: {progress.elapsed_seconds:.1f} seconds")
    
    # Export results
    scraper.export_results("batch_results.csv")
    print("\nResults exported to batch_results.csv")
    
    # Retry failed downloads
    if progress.failed > 0:
        print(f"\nRetrying {progress.failed} failed downloads...")
        retry_results = scraper.retry_failed()
        print(f"Retry complete: {sum(1 for r in retry_results if r.success)} recovered")


if __name__ == "__main__":
    main()

