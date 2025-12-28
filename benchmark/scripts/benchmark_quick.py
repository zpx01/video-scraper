#!/usr/bin/env python3
"""
Quick performance benchmark for YouTube Crawler.

Runs a smaller test set to quickly visualize scaling characteristics.
"""

import gc
import json
import os
import sys
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import numpy as np


@dataclass
class BenchmarkResult:
    workers: int
    rate_limit: float
    videos_processed: int
    elapsed_seconds: float
    throughput: float
    efficiency: float
    errors: int
    peak_memory_mb: float


def run_benchmark(workers: int, rate_limit: float, max_videos: int, seeds: List[str]) -> BenchmarkResult:
    """Run a single benchmark."""
    from videoscraper.crawler import YouTubeCrawler
    
    gc.collect()
    tracemalloc.start()
    
    crawler = YouTubeCrawler(
        max_videos=max_videos,
        max_depth=5,
        num_workers=workers,
        download=False,
        output_dir=f"./bench_temp/w{workers}",
        checkpoint_file=None,
        rate_limit_per_worker=rate_limit,
    )
    
    for url in seeds:
        crawler.add_seed(url)
    
    start = time.time()
    stats = crawler.run()
    elapsed = time.time() - start
    
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    throughput = stats.videos_processed / elapsed if elapsed > 0 else 0
    
    return BenchmarkResult(
        workers=workers,
        rate_limit=rate_limit,
        videos_processed=stats.videos_processed,
        elapsed_seconds=elapsed,
        throughput=throughput,
        efficiency=throughput / workers if workers > 0 else 0,
        errors=stats.errors,
        peak_memory_mb=peak / (1024 * 1024),
    )


def main():
    print("=" * 60)
    print("Quick YouTube Crawler Benchmark")
    print("=" * 60)
    
    # Quick test: fewer configurations
    worker_counts = [1, 2, 4, 8]
    rate_limit = 1.0  # Fixed rate limit
    max_videos = 20  # Quick test
    
    seeds = [
        "https://www.youtube.com/watch?v=XALBGkjkUPQ",
        "https://www.youtube.com/watch?v=3iH8l6dN6Ow",
    ]
    
    print(f"\nTesting worker counts: {worker_counts}")
    print(f"Videos per run: {max_videos}")
    print(f"Rate limit: {rate_limit} req/s/worker")
    print()
    
    results = []
    
    for workers in worker_counts:
        print(f"[{workers} workers] Running...", end=" ", flush=True)
        
        try:
            result = run_benchmark(workers, rate_limit, max_videos, seeds)
            results.append(result)
            print(f"✓ {result.throughput:.2f} videos/sec ({result.elapsed_seconds:.1f}s)")
        except Exception as e:
            print(f"✗ Error: {e}")
        
        time.sleep(1)
    
    if not results:
        print("No results!")
        return 1
    
    # Generate chart
    output_dir = Path("./benchmark_results")
    output_dir.mkdir(exist_ok=True)
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle('YouTube Crawler Scaling Performance', fontsize=14, fontweight='bold')
    
    workers = [r.workers for r in results]
    throughputs = [r.throughput for r in results]
    efficiencies = [r.efficiency for r in results]
    memories = [r.peak_memory_mb for r in results]
    
    # Chart 1: Throughput vs Workers
    ax1 = axes[0]
    ax1.bar(workers, throughputs, color='steelblue', edgecolor='black')
    ax1.plot(workers, throughputs, 'ro-', markersize=8, linewidth=2)
    
    # Ideal linear scaling
    base = throughputs[0]
    ideal = [base * w for w in workers]
    ax1.plot(workers, ideal, 'g--', alpha=0.5, label='Ideal linear')
    
    ax1.set_xlabel('Number of Workers')
    ax1.set_ylabel('Throughput (videos/sec)')
    ax1.set_title('Throughput Scaling')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Chart 2: Efficiency vs Workers  
    ax2 = axes[1]
    ax2.bar(workers, efficiencies, color='forestgreen', edgecolor='black')
    ax2.plot(workers, efficiencies, 'ro-', markersize=8, linewidth=2)
    ax2.axhline(y=efficiencies[0], color='orange', linestyle='--', alpha=0.7, label='Single worker efficiency')
    ax2.set_xlabel('Number of Workers')
    ax2.set_ylabel('Efficiency (videos/worker/sec)')
    ax2.set_title('Worker Efficiency')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # Chart 3: Memory vs Workers
    ax3 = axes[2]
    ax3.bar(workers, memories, color='coral', edgecolor='black')
    ax3.plot(workers, memories, 'ro-', markersize=8, linewidth=2)
    ax3.set_xlabel('Number of Workers')
    ax3.set_ylabel('Peak Memory (MB)')
    ax3.set_title('Memory Usage')
    ax3.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    chart_path = output_dir / "scaling_benchmark.png"
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"\n📊 Chart saved to: {chart_path}")
    
    # Summary
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    print(f"{'Workers':>8} {'Throughput':>15} {'Efficiency':>15} {'Memory':>12}")
    print("-" * 60)
    for r in results:
        print(f"{r.workers:>8} {r.throughput:>12.2f} v/s {r.efficiency:>12.3f} v/w/s {r.peak_memory_mb:>10.1f} MB")
    
    # Scaling analysis
    print("\n📈 Scaling Analysis:")
    if len(results) >= 2:
        speedup = results[-1].throughput / results[0].throughput
        ideal_speedup = results[-1].workers / results[0].workers
        efficiency = speedup / ideal_speedup * 100
        
        print(f"   Speedup ({results[0].workers} → {results[-1].workers} workers): {speedup:.1f}x")
        print(f"   Ideal speedup: {ideal_speedup:.1f}x")
        print(f"   Scaling efficiency: {efficiency:.0f}%")
    
    # Extrapolations
    best = max(results, key=lambda x: x.throughput)
    print(f"\n🚀 Estimated crawl times at {best.throughput:.1f} videos/sec:")
    print(f"   10,000 videos: {10000/best.throughput/60:.0f} minutes")
    print(f"   100,000 videos: {100000/best.throughput/3600:.1f} hours")
    print(f"   1,000,000 videos: {1000000/best.throughput/86400:.1f} days")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

