#!/usr/bin/env python3
"""
GCP Batch Performance Test
==========================

Tests the deployed VideoScraper on GCP by submitting batch jobs
through Pub/Sub and measuring performance.

Usage:
    python demo/gcp_batch_test.py --project YOUR_PROJECT --topic scrape-urls --count 10

Requirements:
    pip install google-cloud-pubsub google-cloud-storage
"""

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    from google.cloud import pubsub_v1
    from google.cloud import storage
except ImportError:
    print("Error: Google Cloud libraries not installed")
    print("Run: pip install google-cloud-pubsub google-cloud-storage")
    sys.exit(1)


@dataclass
class JobResult:
    """Result of a submitted job."""
    job_id: str
    url: str
    submitted_at: float
    completed_at: Optional[float] = None
    success: Optional[bool] = None
    gcs_path: Optional[str] = None
    size_bytes: Optional[int] = None
    error: Optional[str] = None


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


# Test URLs for batch processing
TEST_VIDEO_URLS = [
    # Short Creative Commons YouTube videos
    "https://www.youtube.com/watch?v=BaW_jenozKc",  # 10 sec CC video
    "https://www.youtube.com/watch?v=XALBGkjkUPQ",  # Short sample
    "https://www.youtube.com/watch?v=aqz-KE-bpKQ",  # Big Buck Bunny trailer
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Well-known test video
    "https://www.youtube.com/watch?v=oHg5SJYRHA0",  # Another test
    # Add more test URLs as needed
]


def print_header(text: str):
    """Print styled header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}  {text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")


def publish_job(
    publisher: pubsub_v1.PublisherClient,
    topic_path: str,
    url: str,
    job_id: str
) -> JobResult:
    """Publish a single scraping job to Pub/Sub."""
    message = {
        "url": url,
        "job_id": job_id,
    }
    
    data = json.dumps(message).encode("utf-8")
    future = publisher.publish(topic_path, data)
    future.result()  # Wait for publish to complete
    
    return JobResult(
        job_id=job_id,
        url=url,
        submitted_at=time.time()
    )


def check_gcs_for_results(
    bucket_name: str,
    job_ids: List[str],
    timeout_secs: int = 300
) -> Dict[str, Dict[str, Any]]:
    """Poll GCS for job results."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    results = {}
    start_time = time.time()
    
    print(f"\n{Colors.CYAN}Waiting for results in gs://{bucket_name}/videos/...{Colors.END}")
    
    pending = set(job_ids)
    
    while pending and (time.time() - start_time) < timeout_secs:
        for job_id in list(pending):
            prefix = f"videos/{job_id}/"
            blobs = list(bucket.list_blobs(prefix=prefix))
            
            if blobs:
                blob = blobs[0]
                results[job_id] = {
                    "success": True,
                    "gcs_path": f"gs://{bucket_name}/{blob.name}",
                    "size_bytes": blob.size,
                    "completed_at": time.time()
                }
                pending.remove(job_id)
                print(f"  {Colors.GREEN}✓{Colors.END} {job_id}: {blob.size / 1024 / 1024:.1f} MB")
        
        if pending:
            time.sleep(5)
            elapsed = time.time() - start_time
            print(f"  {Colors.YELLOW}⏳{Colors.END} Waiting... ({len(pending)} pending, {elapsed:.0f}s elapsed)", end="\r")
    
    print()  # New line
    
    # Mark remaining as failed
    for job_id in pending:
        results[job_id] = {
            "success": False,
            "error": "Timeout waiting for result"
        }
    
    return results


def run_batch_test(
    project_id: str,
    topic_name: str,
    bucket_name: str,
    num_jobs: int,
    wait_for_results: bool = True
) -> List[JobResult]:
    """Run a batch of scraping jobs."""
    
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, topic_name)
    
    # Generate job IDs
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    jobs = []
    
    # Cycle through test URLs
    urls_to_use = []
    for i in range(num_jobs):
        urls_to_use.append(TEST_VIDEO_URLS[i % len(TEST_VIDEO_URLS)])
    
    print(f"\n{Colors.CYAN}Submitting {num_jobs} jobs to Pub/Sub...{Colors.END}")
    
    start_time = time.time()
    
    for i, url in enumerate(urls_to_use):
        job_id = f"{batch_id}_{i:04d}"
        job = publish_job(publisher, topic_path, url, job_id)
        jobs.append(job)
        
        print(f"  {Colors.GREEN}✓{Colors.END} {job_id} → {url[:50]}...")
    
    submit_time = time.time() - start_time
    print(f"\n  Submitted {num_jobs} jobs in {submit_time:.2f}s")
    print(f"  Rate: {num_jobs / submit_time:.1f} jobs/sec")
    
    if wait_for_results:
        job_ids = [j.job_id for j in jobs]
        results = check_gcs_for_results(bucket_name, job_ids, timeout_secs=600)
        
        # Update jobs with results
        for job in jobs:
            if job.job_id in results:
                result = results[job.job_id]
                job.success = result.get("success", False)
                job.gcs_path = result.get("gcs_path")
                job.size_bytes = result.get("size_bytes")
                job.error = result.get("error")
                job.completed_at = result.get("completed_at")
    
    return jobs


def print_summary(jobs: List[JobResult]):
    """Print batch test summary."""
    
    successful = [j for j in jobs if j.success]
    failed = [j for j in jobs if j.success is False]
    pending = [j for j in jobs if j.success is None]
    
    total_bytes = sum(j.size_bytes or 0 for j in successful)
    
    print_header("Batch Test Summary")
    
    print(f"  Total Jobs: {len(jobs)}")
    print(f"  {Colors.GREEN}Successful: {len(successful)}{Colors.END}")
    print(f"  {Colors.RED}Failed: {len(failed)}{Colors.END}")
    print(f"  {Colors.YELLOW}Pending: {len(pending)}{Colors.END}")
    print()
    
    if successful:
        durations = [
            (j.completed_at - j.submitted_at) 
            for j in successful 
            if j.completed_at
        ]
        
        if durations:
            avg_duration = sum(durations) / len(durations)
            print(f"  Avg Processing Time: {avg_duration:.1f}s per video")
            print(f"  Total Bytes: {total_bytes / 1024 / 1024:.1f} MB")
            print(f"  Throughput: {len(successful) / (durations[-1] if durations else 1):.2f} videos/min")
    
    if failed:
        print(f"\n  {Colors.RED}Failed Jobs:{Colors.END}")
        for job in failed[:5]:
            print(f"    - {job.job_id}: {job.error}")
        if len(failed) > 5:
            print(f"    ... and {len(failed) - 5} more")


def main():
    parser = argparse.ArgumentParser(description="GCP Batch Performance Test")
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument("--topic", default="scrape-urls", help="Pub/Sub topic name")
    parser.add_argument("--bucket", default=None, help="GCS bucket (default: videoscraper-demo-{project})")
    parser.add_argument("--count", type=int, default=5, help="Number of jobs to submit")
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for results")
    
    args = parser.parse_args()
    
    bucket_name = args.bucket or f"videoscraper-demo-{args.project}"
    
    print_header("GCP Batch Performance Test")
    
    print(f"  Project: {args.project}")
    print(f"  Topic: {args.topic}")
    print(f"  Bucket: {bucket_name}")
    print(f"  Jobs: {args.count}")
    
    try:
        jobs = run_batch_test(
            project_id=args.project,
            topic_name=args.topic,
            bucket_name=bucket_name,
            num_jobs=args.count,
            wait_for_results=not args.no_wait
        )
        
        if not args.no_wait:
            print_summary(jobs)
        else:
            print(f"\n{Colors.GREEN}✓ Jobs submitted. Check GCS for results.{Colors.END}")
            print(f"  gsutil ls gs://{bucket_name}/videos/")
        
        return 0
        
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.END}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

