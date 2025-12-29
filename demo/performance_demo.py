#!/usr/bin/env python3
"""
VideoScraper Performance Demo
=============================

This script demonstrates VideoScraper's performance capabilities by:

1. Downloading multiple test videos concurrently
2. Measuring throughput, latency, and efficiency
3. Testing different concurrency configurations
4. Generating a performance report

This helps validate the system before GCP deployment and gives you
baseline performance metrics for comparison.

Usage:
    python demo/performance_demo.py [--videos N] [--workers W]
    
Examples:
    # Quick demo (3 videos)
    python demo/performance_demo.py
    
    # Full benchmark (10 videos, 8 workers)
    python demo/performance_demo.py --videos 10 --workers 8
"""

import argparse
import json
import os
import sys
import time
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


@dataclass
class DownloadMetrics:
    """Metrics for a single download."""
    url: str
    success: bool
    size_bytes: int
    duration_secs: float
    speed_mbps: float
    error: Optional[str] = None


@dataclass
class PerformanceReport:
    """Overall performance report."""
    total_downloads: int
    successful_downloads: int
    failed_downloads: int
    total_bytes: int
    total_duration_secs: float
    avg_speed_mbps: float
    peak_speed_mbps: float
    min_speed_mbps: float
    concurrency_used: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_downloads": self.total_downloads,
            "successful_downloads": self.successful_downloads,
            "failed_downloads": self.failed_downloads,
            "total_bytes": self.total_bytes,
            "total_bytes_formatted": format_bytes(self.total_bytes),
            "total_duration_secs": round(self.total_duration_secs, 2),
            "avg_speed_mbps": round(self.avg_speed_mbps, 2),
            "peak_speed_mbps": round(self.peak_speed_mbps, 2),
            "min_speed_mbps": round(self.min_speed_mbps, 2),
            "concurrency_used": self.concurrency_used,
            "timestamp": self.timestamp,
        }


class Colors:
    """ANSI color codes."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    END = '\033[0m'


def format_bytes(size: int) -> str:
    """Format bytes to human readable."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def print_header(text: str):
    """Print a styled header."""
    print(f"\n{Colors.BOLD}{Colors.MAGENTA}{'━'*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.MAGENTA}  {text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.MAGENTA}{'━'*60}{Colors.END}\n")


def print_progress(current: int, total: int, metrics: Optional[DownloadMetrics] = None):
    """Print download progress."""
    pct = (current / total) * 100
    bar_len = 30
    filled = int(bar_len * current // total)
    bar = '█' * filled + '░' * (bar_len - filled)
    
    status = f"{Colors.GREEN}✓{Colors.END}" if metrics and metrics.success else f"{Colors.YELLOW}⋯{Colors.END}"
    speed = f"{metrics.speed_mbps:.1f} MB/s" if metrics else "..."
    
    print(f"\r  {status} [{bar}] {current}/{total} ({pct:.0f}%) - {speed}", end='', flush=True)


# Test video URLs (public domain / CC licensed short videos)
# These are small test files that are safe to download for benchmarking
TEST_URLS = [
    # HTTPBin endpoints for testing (generate random bytes)
    ("https://httpbin.org/bytes/1048576", "test_1mb_1.bin"),     # 1MB
    ("https://httpbin.org/bytes/1048576", "test_1mb_2.bin"),     # 1MB
    ("https://httpbin.org/bytes/2097152", "test_2mb_1.bin"),     # 2MB
    ("https://httpbin.org/bytes/2097152", "test_2mb_2.bin"),     # 2MB
    ("https://httpbin.org/bytes/524288", "test_512kb_1.bin"),    # 512KB
    ("https://httpbin.org/bytes/524288", "test_512kb_2.bin"),    # 512KB
    ("https://httpbin.org/bytes/524288", "test_512kb_3.bin"),    # 512KB
    ("https://httpbin.org/bytes/524288", "test_512kb_4.bin"),    # 512KB
    ("https://httpbin.org/bytes/1048576", "test_1mb_3.bin"),     # 1MB
    ("https://httpbin.org/bytes/1048576", "test_1mb_4.bin"),     # 1MB
]


def run_sequential_benchmark(num_downloads: int, output_dir: str) -> PerformanceReport:
    """Run downloads sequentially for baseline comparison."""
    from videoscraper import DownloadManager, ScraperConfig
    
    print(f"\n{Colors.CYAN}Running sequential benchmark (baseline)...{Colors.END}")
    
    config = ScraperConfig()
    manager = DownloadManager(config)
    
    metrics = []
    urls_to_use = TEST_URLS[:num_downloads]
    
    start_time = time.time()
    
    for i, (url, filename) in enumerate(urls_to_use):
        output_path = f"{output_dir}/sequential/{filename}"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        try:
            result = manager.download(url, output_path)
            
            metric = DownloadMetrics(
                url=url,
                success=True,
                size_bytes=result.size_bytes,
                duration_secs=result.duration_secs,
                speed_mbps=(result.size_bytes / 1024 / 1024) / max(result.duration_secs, 0.001)
            )
        except Exception as e:
            metric = DownloadMetrics(
                url=url,
                success=False,
                size_bytes=0,
                duration_secs=0,
                speed_mbps=0,
                error=str(e)
            )
        
        metrics.append(metric)
        print_progress(i + 1, len(urls_to_use), metric)
    
    print()  # New line after progress
    total_duration = time.time() - start_time
    
    return generate_report(metrics, total_duration, concurrency=1)


def run_concurrent_benchmark(num_downloads: int, num_workers: int, output_dir: str) -> PerformanceReport:
    """Run downloads concurrently with specified worker count."""
    from videoscraper import DownloadManager, ScraperConfig
    
    print(f"\n{Colors.CYAN}Running concurrent benchmark ({num_workers} workers)...{Colors.END}")
    
    config = ScraperConfig.high_performance()
    config.max_concurrent_downloads = num_workers
    manager = DownloadManager(config)
    
    urls_to_use = TEST_URLS[:num_downloads]
    items = []
    
    for url, filename in urls_to_use:
        output_path = f"{output_dir}/concurrent/{filename}"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        items.append((url, output_path))
    
    start_time = time.time()
    results = manager.download_batch(items)
    total_duration = time.time() - start_time
    
    metrics = []
    for result in results:
        metric = DownloadMetrics(
            url=result.url,
            success=True,
            size_bytes=result.size_bytes,
            duration_secs=result.duration_secs,
            speed_mbps=(result.size_bytes / 1024 / 1024) / max(result.duration_secs, 0.001)
        )
        metrics.append(metric)
    
    # Print final progress
    print(f"  {Colors.GREEN}✓{Colors.END} Downloaded {len(results)} files in {total_duration:.2f}s")
    
    return generate_report(metrics, total_duration, concurrency=num_workers)


def generate_report(metrics: List[DownloadMetrics], total_duration: float, concurrency: int) -> PerformanceReport:
    """Generate a performance report from metrics."""
    successful = [m for m in metrics if m.success]
    failed = [m for m in metrics if not m.success]
    
    total_bytes = sum(m.size_bytes for m in successful)
    speeds = [m.speed_mbps for m in successful if m.speed_mbps > 0]
    
    return PerformanceReport(
        total_downloads=len(metrics),
        successful_downloads=len(successful),
        failed_downloads=len(failed),
        total_bytes=total_bytes,
        total_duration_secs=total_duration,
        avg_speed_mbps=sum(speeds) / len(speeds) if speeds else 0,
        peak_speed_mbps=max(speeds) if speeds else 0,
        min_speed_mbps=min(speeds) if speeds else 0,
        concurrency_used=concurrency,
    )


def print_report(report: PerformanceReport, title: str):
    """Print a formatted performance report."""
    print(f"\n  {Colors.BOLD}{title}{Colors.END}")
    print(f"  {'─'*40}")
    print(f"  Downloads: {Colors.GREEN}{report.successful_downloads}{Colors.END}/{report.total_downloads} succeeded")
    print(f"  Total Size: {format_bytes(report.total_bytes)}")
    print(f"  Duration: {report.total_duration_secs:.2f}s")
    print(f"  Throughput: {Colors.CYAN}{(report.total_bytes / 1024 / 1024) / report.total_duration_secs:.2f} MB/s{Colors.END}")
    print(f"  Avg Speed: {report.avg_speed_mbps:.2f} MB/s")
    if report.concurrency_used > 1:
        print(f"  Concurrency: {report.concurrency_used} workers")


def run_youtube_demo(output_dir: str) -> Optional[DownloadMetrics]:
    """Demo YouTube download (if yt-dlp available)."""
    try:
        import yt_dlp
    except ImportError:
        print(f"  {Colors.YELLOW}⚠ yt-dlp not installed, skipping YouTube demo{Colors.END}")
        return None
    
    from videoscraper.sites import YouTubeScraper
    
    print(f"\n{Colors.CYAN}Testing YouTube download...{Colors.END}")
    
    # Use a short Creative Commons video for testing
    test_url = "https://www.youtube.com/watch?v=BaW_jenozKc"  # Short CC video
    
    try:
        scraper = YouTubeScraper(
            output_dir=f"{output_dir}/youtube",
            quality="360p",  # Low quality for quick test
            format="mp4",
        )
        
        start = time.time()
        result = scraper.download(test_url)
        duration = time.time() - start
        
        if result.success:
            file_size = os.path.getsize(result.output_path) if result.output_path else 0
            speed = (file_size / 1024 / 1024) / max(duration, 0.001)
            
            print(f"  {Colors.GREEN}✓{Colors.END} YouTube download successful!")
            print(f"    Size: {format_bytes(file_size)}")
            print(f"    Duration: {duration:.1f}s")
            print(f"    Speed: {speed:.1f} MB/s")
            
            return DownloadMetrics(
                url=test_url,
                success=True,
                size_bytes=file_size,
                duration_secs=duration,
                speed_mbps=speed
            )
        else:
            print(f"  {Colors.RED}✗{Colors.END} YouTube download failed: {result.error}")
            return None
            
    except Exception as e:
        print(f"  {Colors.RED}✗{Colors.END} YouTube test error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="VideoScraper Performance Demo")
    parser.add_argument("--videos", type=int, default=5, help="Number of test files to download")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers")
    parser.add_argument("--output", type=str, default=None, help="Output directory (temp if not specified)")
    parser.add_argument("--youtube", action="store_true", help="Include YouTube download test")
    parser.add_argument("--json", type=str, default=None, help="Export results to JSON file")
    
    args = parser.parse_args()
    
    print_header("VideoScraper Performance Demo")
    
    # Verify setup
    print(f"{Colors.CYAN}Verifying setup...{Colors.END}")
    try:
        from videoscraper import __version__
        print(f"  {Colors.GREEN}✓{Colors.END} VideoScraper version: {__version__}")
    except ImportError as e:
        print(f"  {Colors.RED}✗{Colors.END} VideoScraper not installed: {e}")
        print(f"\n{Colors.YELLOW}Run 'make dev' or 'maturin develop' first.{Colors.END}")
        return 1
    
    # Setup output directory
    if args.output:
        output_dir = args.output
        os.makedirs(output_dir, exist_ok=True)
    else:
        output_dir = tempfile.mkdtemp(prefix="videoscraper_demo_")
    
    print(f"  Output directory: {output_dir}")
    print(f"  Test downloads: {args.videos}")
    print(f"  Worker count: {args.workers}")
    
    # Limit to available test URLs
    num_downloads = min(args.videos, len(TEST_URLS))
    if num_downloads != args.videos:
        print(f"  {Colors.YELLOW}Note: Limiting to {num_downloads} downloads (max available){Colors.END}")
    
    print_header("Benchmark Results")
    
    # Run sequential benchmark (baseline)
    sequential_report = run_sequential_benchmark(num_downloads, output_dir)
    print_report(sequential_report, "Sequential (Baseline)")
    
    # Run concurrent benchmark
    concurrent_report = run_concurrent_benchmark(num_downloads, args.workers, output_dir)
    print_report(concurrent_report, f"Concurrent ({args.workers} workers)")
    
    # Calculate speedup
    if sequential_report.total_duration_secs > 0:
        speedup = sequential_report.total_duration_secs / concurrent_report.total_duration_secs
        print(f"\n  {Colors.GREEN}Speedup: {speedup:.2f}x faster with {args.workers} workers{Colors.END}")
    
    # YouTube test
    youtube_result = None
    if args.youtube:
        youtube_result = run_youtube_demo(output_dir)
    
    # Summary
    print_header("Performance Summary")
    
    concurrent_throughput = (concurrent_report.total_bytes / 1024 / 1024) / concurrent_report.total_duration_secs
    
    print(f"  {Colors.BOLD}Concurrent Performance:{Colors.END}")
    print(f"    • Throughput: {Colors.GREEN}{concurrent_throughput:.2f} MB/s{Colors.END}")
    print(f"    • Downloads: {concurrent_report.successful_downloads}/{concurrent_report.total_downloads}")
    print(f"    • Total Time: {concurrent_report.total_duration_secs:.2f}s")
    
    print(f"\n  {Colors.BOLD}Scaling Estimates (extrapolated):{Colors.END}")
    videos_per_sec = concurrent_report.successful_downloads / concurrent_report.total_duration_secs
    print(f"    • 100 videos: ~{100 / videos_per_sec / 60:.1f} minutes")
    print(f"    • 1,000 videos: ~{1000 / videos_per_sec / 3600:.1f} hours")
    print(f"    • 10,000 videos: ~{10000 / videos_per_sec / 3600:.1f} hours")
    
    # Export to JSON if requested
    if args.json:
        results = {
            "timestamp": datetime.now().isoformat(),
            "config": {
                "num_downloads": num_downloads,
                "num_workers": args.workers,
            },
            "sequential": sequential_report.to_dict(),
            "concurrent": concurrent_report.to_dict(),
            "youtube": youtube_result.__dict__ if youtube_result else None,
        }
        
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n  {Colors.CYAN}Results exported to: {args.json}{Colors.END}")
    
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Performance demo complete!{Colors.END}")
    print(f"\n{Colors.CYAN}Next steps:{Colors.END}")
    print("  1. Deploy to GCP: cd deploy/gcp && ./deploy.sh")
    print("  2. Read the guide: demo/GCP_DEMO_GUIDE.md")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

