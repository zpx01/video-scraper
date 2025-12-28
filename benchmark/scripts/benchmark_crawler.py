#!/usr/bin/env python3
"""
Performance benchmark for YouTube Crawler.

Tests different configurations to find optimal scaling parameters
and generates Pareto frontier visualization.

Metrics:
- Throughput (videos/second)
- Worker efficiency (videos/worker/second)
- Error rate
- Memory usage
"""

import gc
import json
import os
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple

import matplotlib.pyplot as plt
import numpy as np


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""
    workers: int
    rate_limit: float
    max_videos: int
    videos_discovered: int
    videos_processed: int
    errors: int
    elapsed_seconds: float
    throughput: float  # videos/sec
    efficiency: float  # videos/worker/sec
    error_rate: float  # errors/total
    peak_memory_mb: float
    
    def to_dict(self) -> dict:
        return {
            "workers": self.workers,
            "rate_limit": self.rate_limit,
            "max_videos": self.max_videos,
            "videos_discovered": self.videos_discovered,
            "videos_processed": self.videos_processed,
            "errors": self.errors,
            "elapsed_seconds": self.elapsed_seconds,
            "throughput": self.throughput,
            "efficiency": self.efficiency,
            "error_rate": self.error_rate,
            "peak_memory_mb": self.peak_memory_mb,
        }


def run_single_benchmark(
    workers: int,
    rate_limit: float,
    max_videos: int,
    seed_urls: List[str],
) -> BenchmarkResult:
    """Run a single benchmark with given parameters."""
    from videoscraper.crawler import YouTubeCrawler
    
    # Force garbage collection
    gc.collect()
    
    # Start memory tracking
    tracemalloc.start()
    
    output_dir = Path(f"./benchmark_runs/w{workers}_r{rate_limit}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    crawler = YouTubeCrawler(
        max_videos=max_videos,
        max_depth=10,
        num_workers=workers,
        download=False,
        output_dir=str(output_dir),
        checkpoint_file=None,  # No checkpointing for benchmark
        random_walk_prob=0.8,
        rate_limit_per_worker=rate_limit,
    )
    
    # Add seeds
    for url in seed_urls:
        crawler.add_seed(url)
    
    # Run crawler
    start_time = time.time()
    stats = crawler.run()
    elapsed = time.time() - start_time
    
    # Get memory stats
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Calculate metrics
    throughput = stats.videos_processed / elapsed if elapsed > 0 else 0
    efficiency = throughput / workers if workers > 0 else 0
    error_rate = stats.errors / max(stats.videos_processed, 1)
    
    return BenchmarkResult(
        workers=workers,
        rate_limit=rate_limit,
        max_videos=max_videos,
        videos_discovered=stats.videos_discovered,
        videos_processed=stats.videos_processed,
        errors=stats.errors,
        elapsed_seconds=elapsed,
        throughput=throughput,
        efficiency=efficiency,
        error_rate=error_rate,
        peak_memory_mb=peak / (1024 * 1024),
    )


def run_benchmark_suite(
    worker_counts: List[int],
    rate_limits: List[float],
    max_videos: int,
    seed_urls: List[str],
) -> List[BenchmarkResult]:
    """Run benchmark across multiple configurations."""
    results = []
    total_runs = len(worker_counts) * len(rate_limits)
    run_num = 0
    
    for workers in worker_counts:
        for rate_limit in rate_limits:
            run_num += 1
            print(f"\n[{run_num}/{total_runs}] Testing: {workers} workers, {rate_limit} req/s/worker")
            print("-" * 50)
            
            try:
                result = run_single_benchmark(
                    workers=workers,
                    rate_limit=rate_limit,
                    max_videos=max_videos,
                    seed_urls=seed_urls,
                )
                results.append(result)
                
                print(f"  ✓ Throughput: {result.throughput:.2f} videos/sec")
                print(f"  ✓ Efficiency: {result.efficiency:.3f} videos/worker/sec")
                print(f"  ✓ Errors: {result.errors} ({result.error_rate*100:.1f}%)")
                print(f"  ✓ Memory: {result.peak_memory_mb:.1f} MB")
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                traceback_str = traceback.format_exc()
                print(traceback_str[:500])
            
            # Cool down between runs
            time.sleep(2)
    
    return results


def find_pareto_frontier(results: List[BenchmarkResult]) -> List[BenchmarkResult]:
    """
    Find Pareto-optimal configurations.
    
    A configuration is Pareto-optimal if no other configuration
    is better in all objectives (throughput, efficiency, -errors, -memory).
    """
    pareto = []
    
    for candidate in results:
        is_dominated = False
        
        for other in results:
            if other is candidate:
                continue
            
            # Check if 'other' dominates 'candidate'
            # Other is better or equal in all objectives AND strictly better in at least one
            better_throughput = other.throughput >= candidate.throughput
            better_efficiency = other.efficiency >= candidate.efficiency
            better_errors = other.error_rate <= candidate.error_rate
            better_memory = other.peak_memory_mb <= candidate.peak_memory_mb
            
            all_better_or_equal = (
                better_throughput and better_efficiency and 
                better_errors and better_memory
            )
            
            strictly_better = (
                other.throughput > candidate.throughput or
                other.efficiency > candidate.efficiency or
                other.error_rate < candidate.error_rate or
                other.peak_memory_mb < candidate.peak_memory_mb
            )
            
            if all_better_or_equal and strictly_better:
                is_dominated = True
                break
        
        if not is_dominated:
            pareto.append(candidate)
    
    return pareto


def plot_results(results: List[BenchmarkResult], output_path: str):
    """Generate visualization of benchmark results."""
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('YouTube Crawler Performance Benchmark', fontsize=14, fontweight='bold')
    
    # Extract data
    workers = [r.workers for r in results]
    throughputs = [r.throughput for r in results]
    efficiencies = [r.efficiency for r in results]
    error_rates = [r.error_rate * 100 for r in results]
    memories = [r.peak_memory_mb for r in results]
    rate_limits = [r.rate_limit for r in results]
    
    # Find Pareto frontier
    pareto = find_pareto_frontier(results)
    pareto_workers = [r.workers for r in pareto]
    pareto_throughputs = [r.throughput for r in pareto]
    pareto_efficiencies = [r.efficiency for r in pareto]
    
    # Color by rate limit
    unique_rates = sorted(set(rate_limits))
    colors = plt.cm.viridis(np.linspace(0, 1, len(unique_rates)))
    color_map = {rate: colors[i] for i, rate in enumerate(unique_rates)}
    point_colors = [color_map[r] for r in rate_limits]
    
    # Plot 1: Workers vs Throughput
    ax1 = axes[0, 0]
    scatter1 = ax1.scatter(workers, throughputs, c=point_colors, s=100, alpha=0.7, edgecolors='black')
    ax1.plot(pareto_workers, pareto_throughputs, 'r--', linewidth=2, label='Pareto Frontier', alpha=0.7)
    ax1.scatter(pareto_workers, pareto_throughputs, c='red', s=150, marker='*', zorder=5, label='Pareto Optimal')
    ax1.set_xlabel('Number of Workers', fontsize=11)
    ax1.set_ylabel('Throughput (videos/sec)', fontsize=11)
    ax1.set_title('Throughput vs Workers', fontsize=12)
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Workers vs Efficiency
    ax2 = axes[0, 1]
    ax2.scatter(workers, efficiencies, c=point_colors, s=100, alpha=0.7, edgecolors='black')
    ax2.scatter(pareto_workers, pareto_efficiencies, c='red', s=150, marker='*', zorder=5)
    ax2.set_xlabel('Number of Workers', fontsize=11)
    ax2.set_ylabel('Efficiency (videos/worker/sec)', fontsize=11)
    ax2.set_title('Worker Efficiency vs Workers', fontsize=12)
    ax2.grid(True, alpha=0.3)
    
    # Plot 3: Throughput vs Memory (Pareto frontier)
    ax3 = axes[1, 0]
    ax3.scatter(memories, throughputs, c=point_colors, s=100, alpha=0.7, edgecolors='black')
    for r in pareto:
        ax3.scatter(r.peak_memory_mb, r.throughput, c='red', s=150, marker='*', zorder=5)
    ax3.set_xlabel('Peak Memory (MB)', fontsize=11)
    ax3.set_ylabel('Throughput (videos/sec)', fontsize=11)
    ax3.set_title('Throughput vs Memory (Pareto Frontier)', fontsize=12)
    ax3.grid(True, alpha=0.3)
    
    # Plot 4: Throughput vs Error Rate
    ax4 = axes[1, 1]
    ax4.scatter(error_rates, throughputs, c=point_colors, s=100, alpha=0.7, edgecolors='black')
    ax4.set_xlabel('Error Rate (%)', fontsize=11)
    ax4.set_ylabel('Throughput (videos/sec)', fontsize=11)
    ax4.set_title('Throughput vs Error Rate', fontsize=12)
    ax4.grid(True, alpha=0.3)
    
    # Add colorbar legend
    sm = plt.cm.ScalarMappable(cmap=plt.cm.viridis, norm=plt.Normalize(min(rate_limits), max(rate_limits)))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=axes, orientation='vertical', fraction=0.02, pad=0.04)
    cbar.set_label('Rate Limit (req/s/worker)', fontsize=10)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"\n📊 Chart saved to: {output_path}")


def plot_scaling_curve(results: List[BenchmarkResult], output_path: str):
    """Plot scaling curve showing throughput vs workers."""
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Group by rate limit
    rate_groups: Dict[float, List[BenchmarkResult]] = {}
    for r in results:
        if r.rate_limit not in rate_groups:
            rate_groups[r.rate_limit] = []
        rate_groups[r.rate_limit].append(r)
    
    colors = plt.cm.tab10(np.linspace(0, 1, len(rate_groups)))
    
    for i, (rate, group) in enumerate(sorted(rate_groups.items())):
        # Sort by workers
        group_sorted = sorted(group, key=lambda x: x.workers)
        workers = [r.workers for r in group_sorted]
        throughputs = [r.throughput for r in group_sorted]
        
        ax.plot(workers, throughputs, 'o-', color=colors[i], linewidth=2, 
                markersize=8, label=f'{rate} req/s/worker')
    
    # Add ideal linear scaling line
    max_workers = max(r.workers for r in results)
    if results:
        base_throughput = min(r.throughput for r in results if r.workers == min(r.workers for r in results))
        ideal_x = range(1, max_workers + 1)
        ideal_y = [base_throughput * w for w in ideal_x]
        ax.plot(ideal_x, ideal_y, 'k--', alpha=0.3, label='Ideal Linear Scaling')
    
    ax.set_xlabel('Number of Workers', fontsize=12)
    ax.set_ylabel('Throughput (videos/sec)', fontsize=12)
    ax.set_title('Crawler Scaling: Throughput vs Workers', fontsize=14, fontweight='bold')
    ax.legend(title='Rate Limit')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"📈 Scaling curve saved to: {output_path}")


def main():
    print("=" * 70)
    print("YouTube Crawler Performance Benchmark")
    print("=" * 70)
    print()
    
    # Check dependencies
    try:
        import matplotlib
        print(f"✓ matplotlib {matplotlib.__version__}")
    except ImportError:
        print("Installing matplotlib...")
        os.system(f"{sys.executable} -m pip install matplotlib -q")
        import matplotlib
    
    # Benchmark parameters
    # Test different worker counts and rate limits
    worker_counts = [1, 2, 4, 8, 12, 16]
    rate_limits = [0.5, 1.0, 2.0]  # requests per second per worker
    max_videos_per_run = 30  # Quick benchmark with 30 videos each
    
    # Seed URLs for consistent testing
    seed_urls = [
        "https://www.youtube.com/watch?v=XALBGkjkUPQ",
        "https://www.youtube.com/watch?v=3iH8l6dN6Ow",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ]
    
    print(f"Configuration:")
    print(f"  Worker counts: {worker_counts}")
    print(f"  Rate limits: {rate_limits} req/s/worker")
    print(f"  Videos per run: {max_videos_per_run}")
    print(f"  Total runs: {len(worker_counts) * len(rate_limits)}")
    print()
    
    # Create output directory
    output_dir = Path("./benchmark_results")
    output_dir.mkdir(exist_ok=True)
    
    # Run benchmarks
    print("Starting benchmark suite...")
    results = run_benchmark_suite(
        worker_counts=worker_counts,
        rate_limits=rate_limits,
        max_videos=max_videos_per_run,
        seed_urls=seed_urls,
    )
    
    if not results:
        print("No benchmark results collected!")
        return 1
    
    # Find Pareto optimal configurations
    pareto = find_pareto_frontier(results)
    
    print("\n" + "=" * 70)
    print("Results Summary")
    print("=" * 70)
    
    # Sort by throughput
    results_sorted = sorted(results, key=lambda x: x.throughput, reverse=True)
    
    print("\nTop 5 configurations by throughput:")
    print("-" * 70)
    print(f"{'Workers':>8} {'Rate':>8} {'Throughput':>12} {'Efficiency':>12} {'Errors':>8} {'Memory':>10}")
    print("-" * 70)
    for r in results_sorted[:5]:
        print(f"{r.workers:>8} {r.rate_limit:>8.1f} {r.throughput:>12.2f} {r.efficiency:>12.3f} {r.errors:>8} {r.peak_memory_mb:>10.1f}")
    
    print("\n⭐ Pareto-optimal configurations:")
    print("-" * 70)
    for r in sorted(pareto, key=lambda x: x.throughput, reverse=True):
        print(f"  Workers: {r.workers}, Rate: {r.rate_limit} → "
              f"Throughput: {r.throughput:.2f} v/s, Efficiency: {r.efficiency:.3f}")
    
    # Save results
    results_file = output_dir / "benchmark_results.json"
    with open(results_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "config": {
                "worker_counts": worker_counts,
                "rate_limits": rate_limits,
                "max_videos": max_videos_per_run,
            },
            "results": [r.to_dict() for r in results],
            "pareto_optimal": [r.to_dict() for r in pareto],
        }, f, indent=2)
    print(f"\n📄 Results saved to: {results_file}")
    
    # Generate charts
    plot_results(results, str(output_dir / "pareto_frontier.png"))
    plot_scaling_curve(results, str(output_dir / "scaling_curve.png"))
    
    # Recommendations
    print("\n" + "=" * 70)
    print("Recommendations")
    print("=" * 70)
    
    if pareto:
        best_throughput = max(pareto, key=lambda x: x.throughput)
        best_efficiency = max(pareto, key=lambda x: x.efficiency)
        
        print(f"\n🚀 For maximum throughput:")
        print(f"   {best_throughput.workers} workers at {best_throughput.rate_limit} req/s/worker")
        print(f"   → {best_throughput.throughput:.2f} videos/sec")
        
        print(f"\n💡 For best efficiency:")
        print(f"   {best_efficiency.workers} workers at {best_efficiency.rate_limit} req/s/worker")
        print(f"   → {best_efficiency.efficiency:.3f} videos/worker/sec")
        
        # Extrapolate scaling
        print(f"\n📊 Scaling estimates (extrapolated):")
        print(f"   1,000 videos: ~{1000/best_throughput.throughput/60:.1f} minutes")
        print(f"   10,000 videos: ~{10000/best_throughput.throughput/3600:.1f} hours")
        print(f"   100,000 videos: ~{100000/best_throughput.throughput/3600:.1f} hours")
        print(f"   1,000,000 videos: ~{1000000/best_throughput.throughput/86400:.1f} days")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

