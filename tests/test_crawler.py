#!/usr/bin/env python3
"""
Test script for YouTube Graph Crawler.

This script demonstrates crawling YouTube's video graph
using random walks from seed videos.

Usage:
    python test_crawler.py
"""

import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def on_video_discovered(node):
    """Callback when a video is discovered."""
    depth_indicator = "→" * node.depth
    print(f"  {depth_indicator} [{node.depth}] {node.title[:50] if node.title else 'Unknown'}...")
    print(f"       ID: {node.video_id}, Related: {len(node.related_ids)} videos")


def main():
    print("=" * 70)
    print("YouTube Graph Crawler - Random Walk Demo")
    print("=" * 70)
    
    # Import crawler
    try:
        from videoscraper.crawler import YouTubeCrawler
    except ImportError as e:
        print(f"Error importing crawler: {e}")
        return 1
    
    # Create output directory
    output_dir = Path("./crawl_test")
    output_dir.mkdir(exist_ok=True)
    
    # Initialize crawler
    crawler = YouTubeCrawler(
        max_videos=20,              # Discover 20 videos for demo
        max_depth=5,                # Max 5 hops from seed
        num_workers=4,              # 4 parallel workers
        download=False,             # Don't download (just discover)
        output_dir=str(output_dir),
        checkpoint_file=str(output_dir / "checkpoint.json"),
        random_walk_prob=0.9,       # 90% chance of random walk
        rate_limit_per_worker=0.5,  # 1 request per 2 seconds per worker
        on_discover=on_video_discovered,
    )
    
    print(f"\n📁 Output directory: {output_dir.absolute()}")
    print(f"🎯 Target: {crawler.max_videos} videos")
    print(f"👷 Workers: {crawler.num_workers}")
    print()
    
    # Add seed videos (the ones you tested earlier)
    seed_urls = [
        "https://www.youtube.com/watch?v=XALBGkjkUPQ",  # Imagine for 1 Minute
        "https://www.youtube.com/watch?v=3iH8l6dN6Ow",  # Live a little
    ]
    
    print("🌱 Adding seed videos...")
    for url in seed_urls:
        crawler.add_seed(url)
    
    print(f"   Added {len(seed_urls)} seeds")
    print()
    
    # Run the crawl
    print("🕷️ Starting crawl...")
    print("-" * 70)
    
    try:
        stats = crawler.run()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
        crawler.stop()
        stats = crawler.stats
    
    print("-" * 70)
    print()
    
    # Summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Videos discovered: {stats.videos_discovered}")
    print(f"Videos processed: {stats.videos_processed}")
    print(f"Errors: {stats.errors}")
    print(f"Time elapsed: {stats.elapsed_seconds:.1f} seconds")
    print(f"Rate: {stats.videos_per_second:.2f} videos/second")
    print()
    
    # Show discovered videos
    print("Discovered videos:")
    for i, node in enumerate(crawler.discovered_videos[:10], 1):
        title = (node.title[:45] + "...") if node.title and len(node.title) > 45 else node.title
        print(f"  {i}. [{node.depth}] {title}")
        print(f"      URL: https://youtube.com/watch?v={node.video_id}")
        print(f"      Channel: {node.channel}, Views: {node.view_count:,}" if node.view_count else f"      Channel: {node.channel}")
    
    if len(crawler.discovered_videos) > 10:
        print(f"  ... and {len(crawler.discovered_videos) - 10} more")
    
    # Export results
    export_file = output_dir / "discovered_videos.json"
    crawler.export(str(export_file))
    print(f"\n📄 Exported to: {export_file}")
    
    # Show graph structure
    print("\n🔗 Graph structure (first 5 paths):")
    paths_shown = 0
    for node in crawler.discovered_videos:
        if node.parent_id and paths_shown < 5:
            parent = crawler._discovered.get(node.parent_id)
            if parent:
                parent_title = (parent.title[:30] + "...") if parent.title and len(parent.title) > 30 else parent.title
                node_title = (node.title[:30] + "...") if node.title and len(node.title) > 30 else node.title
                print(f"   {parent_title} → {node_title}")
                paths_shown += 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

