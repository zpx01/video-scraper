#!/usr/bin/env python3
"""
Distributed scraping example for petabyte-scale collection.

This example shows how to set up VideoScraper for distributed
collection across multiple machines with cloud storage.
"""

import json
import os
from videoscraper import (
    Pipeline,
    ScraperConfig,
    StorageConfig,
    VideoFilter,
)


def setup_s3_storage():
    """Configure S3 storage for distributed collection."""
    return StorageConfig.s3(
        bucket=os.environ.get("S3_BUCKET", "my-video-bucket"),
        region=os.environ.get("AWS_REGION", "us-east-1"),
        key_prefix="scraped-videos/",
    )


def setup_gcs_storage():
    """Configure GCS storage for distributed collection."""
    return StorageConfig.gcs(
        bucket=os.environ.get("GCS_BUCKET", "my-video-bucket"),
        project=os.environ.get("GCP_PROJECT", "my-project"),
        key_prefix="scraped-videos/",
    )


def setup_high_performance_config():
    """Configure for maximum throughput."""
    config = ScraperConfig.high_performance()
    
    # Aggressive concurrency
    config.max_concurrent_downloads = 256
    config.max_requests_per_domain = 16
    
    # Large chunks for efficiency
    config.chunk_size_bytes = 32 * 1024 * 1024  # 32MB
    
    # Fast rate limiting (be careful!)
    config.rate_limit_per_second = 100.0
    config.respect_robots_txt = False
    
    # Generous timeouts
    config.request_timeout_secs = 600
    
    # Many retries with backoff
    config.max_retries = 10
    config.retry_delay_ms = 2000
    
    # Connection pool
    config.pool_size_per_host = 32
    config.idle_timeout_secs = 120
    
    return config


def worker_main(worker_id: int, url_batch: list, storage_config: StorageConfig):
    """
    Main function for a distributed worker.
    
    In production, this would be called by a job scheduler like:
    - Kubernetes Jobs
    - AWS Batch
    - Google Cloud Run
    - Apache Airflow
    """
    print(f"Worker {worker_id} starting with {len(url_batch)} URLs")
    
    # Setup
    config = setup_high_performance_config()
    
    # Create pipeline
    pipeline = Pipeline(config, storage_config)
    
    # Add URLs
    pipeline.add_urls(url_batch)
    
    # Run with high concurrency
    pipeline.run(concurrency=64)
    
    # Get results
    stats = pipeline.stats()
    jobs = pipeline.jobs()
    
    # Report results
    results = {
        "worker_id": worker_id,
        "total": stats.total_jobs,
        "completed": stats.completed_jobs,
        "failed": stats.failed_jobs,
        "bytes_downloaded": stats.total_bytes_downloaded,
        "jobs": [
            {
                "id": j.id,
                "url": j.source_url,
                "status": str(j.status),
                "storage_key": j.storage_key,
                "error": j.error_message,
            }
            for j in jobs
        ]
    }
    
    print(f"Worker {worker_id} complete: {stats.completed_jobs} succeeded, {stats.failed_jobs} failed")
    
    return results


def coordinator_main():
    """
    Main function for the coordinator.
    
    The coordinator:
    1. Loads URLs from a source (file, database, API)
    2. Partitions URLs across workers
    3. Dispatches work to workers
    4. Collects and aggregates results
    """
    # Load URLs (in production, this might be from a database or queue)
    print("Loading URLs...")
    urls = [
        f"https://example.com/video{i}"
        for i in range(10000)  # Example: 10k URLs
    ]
    
    # Partition URLs for workers
    num_workers = 10
    batch_size = len(urls) // num_workers
    
    url_batches = [
        urls[i * batch_size:(i + 1) * batch_size]
        for i in range(num_workers)
    ]
    
    # Handle remainder
    remainder = urls[num_workers * batch_size:]
    if remainder:
        url_batches[-1].extend(remainder)
    
    print(f"Partitioned {len(urls)} URLs across {num_workers} workers")
    
    # In production, dispatch to remote workers
    # For this example, we run locally
    storage_config = setup_s3_storage()
    
    all_results = []
    for worker_id, batch in enumerate(url_batches):
        result = worker_main(worker_id, batch, storage_config)
        all_results.append(result)
    
    # Aggregate results
    total_completed = sum(r["completed"] for r in all_results)
    total_failed = sum(r["failed"] for r in all_results)
    total_bytes = sum(r["bytes_downloaded"] for r in all_results)
    
    print("\n=== Final Aggregated Results ===")
    print(f"Total URLs: {len(urls)}")
    print(f"Completed: {total_completed}")
    print(f"Failed: {total_failed}")
    print(f"Total data: {total_bytes / 1_000_000_000:.2f} GB")
    
    # Save results manifest
    with open("scraping_manifest.json", "w") as f:
        json.dump({
            "total_urls": len(urls),
            "completed": total_completed,
            "failed": total_failed,
            "bytes_downloaded": total_bytes,
            "workers": all_results,
        }, f, indent=2)
    
    print("Results saved to scraping_manifest.json")


def kubernetes_job_example():
    """
    Example of how to structure a Kubernetes job.
    
    In production, you would:
    1. Build a Docker image with videoscraper
    2. Create a Kubernetes Job/CronJob
    3. Use a message queue (SQS, Pub/Sub, Redis) for URL distribution
    """
    kubernetes_job_yaml = """
apiVersion: batch/v1
kind: Job
metadata:
  name: video-scraper-worker
spec:
  parallelism: 10
  completions: 10
  template:
    spec:
      containers:
      - name: scraper
        image: videoscraper:latest
        command: ["python", "-m", "videoscraper.worker"]
        env:
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: S3_BUCKET
          value: "my-video-bucket"
        - name: AWS_REGION
          value: "us-east-1"
        - name: URL_QUEUE
          value: "sqs://video-urls-queue"
        resources:
          requests:
            memory: "2Gi"
            cpu: "2"
          limits:
            memory: "4Gi"
            cpu: "4"
      restartPolicy: OnFailure
    """
    print("Example Kubernetes Job configuration:")
    print(kubernetes_job_yaml)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--k8s-example":
        kubernetes_job_example()
    else:
        # Run local demo
        print("Running distributed scraping demo (local mode)")
        print("For Kubernetes example, run with: --k8s-example\n")
        
        # For demo, just run a single worker with fewer URLs
        storage_config = StorageConfig.local("./distributed_downloads")
        demo_urls = [f"https://example.com/video{i}" for i in range(10)]
        worker_main(0, demo_urls, storage_config)

