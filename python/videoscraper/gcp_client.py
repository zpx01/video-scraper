"""
GCP Client for distributed video scraping.

Publish URLs to the scraping queue and monitor results.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScrapeRequest:
    """Request to scrape a URL."""
    url: str
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int = 0
    options: Dict[str, Any] = field(default_factory=dict)
    
    def to_json(self) -> str:
        return json.dumps({
            "url": self.url,
            "job_id": self.job_id,
            "priority": self.priority,
            "options": self.options,
        })


@dataclass  
class ScrapeResult:
    """Result from a scrape job."""
    job_id: str
    url: str
    status: str  # success, failed, error
    gcs_path: Optional[str] = None
    size_bytes: Optional[int] = None
    title: Optional[str] = None
    duration: Optional[int] = None
    error: Optional[str] = None
    
    @classmethod
    def from_json(cls, data: dict) -> "ScrapeResult":
        return cls(
            job_id=data.get("job_id", ""),
            url=data.get("url", ""),
            status=data.get("status", "unknown"),
            gcs_path=data.get("gcs_path"),
            size_bytes=data.get("size_bytes"),
            title=data.get("title"),
            duration=data.get("duration"),
            error=data.get("error"),
        )


class GCPScraperClient:
    """
    Client for submitting scrape jobs to GCP.
    
    Example:
        >>> from videoscraper.gcp_client import GCPScraperClient
        >>> 
        >>> client = GCPScraperClient(project_id="my-project")
        >>> 
        >>> # Submit single URL
        >>> job_id = client.submit("https://youtube.com/watch?v=VIDEO_ID")
        >>> 
        >>> # Submit batch
        >>> job_ids = client.submit_batch([
        ...     "https://youtube.com/watch?v=VIDEO1",
        ...     "https://youtube.com/watch?v=VIDEO2",
        ... ])
        >>> 
        >>> # Submit from file
        >>> job_ids = client.submit_from_file("urls.txt")
        >>> 
        >>> # Monitor results (blocking)
        >>> for result in client.stream_results():
        ...     print(f"{result.job_id}: {result.status}")
    """
    
    def __init__(
        self,
        project_id: str,
        topic_name: str = "scrape-urls",
        results_subscription: Optional[str] = None,
        region: str = "us-central1",
    ):
        """
        Initialize GCP client.
        
        Args:
            project_id: GCP project ID
            topic_name: Pub/Sub topic for URL submission
            results_subscription: Pub/Sub subscription for results (optional)
            region: GCP region
        """
        try:
            from google.cloud import pubsub_v1
        except ImportError:
            raise ImportError(
                "google-cloud-pubsub is required. "
                "Install with: pip install google-cloud-pubsub"
            )
        
        self.project_id = project_id
        self.topic_name = topic_name
        self.results_subscription = results_subscription
        self.region = region
        
        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(project_id, topic_name)
        
        self._pending_jobs: Dict[str, ScrapeRequest] = {}
        self._completed_jobs: Dict[str, ScrapeResult] = {}
    
    def submit(
        self,
        url: str,
        job_id: Optional[str] = None,
        priority: int = 0,
        **options,
    ) -> str:
        """
        Submit a URL for scraping.
        
        Args:
            url: URL to scrape
            job_id: Optional custom job ID
            priority: Job priority (higher = sooner)
            **options: Additional options (quality, format, etc.)
            
        Returns:
            Job ID
        """
        request = ScrapeRequest(
            url=url,
            job_id=job_id or str(uuid.uuid4()),
            priority=priority,
            options=options,
        )
        
        future = self._publisher.publish(
            self._topic_path,
            request.to_json().encode("utf-8"),
            priority=str(priority),
        )
        
        # Wait for publish to complete
        message_id = future.result()
        logger.info(f"Published job {request.job_id} (message: {message_id})")
        
        self._pending_jobs[request.job_id] = request
        return request.job_id
    
    def submit_batch(
        self,
        urls: List[str],
        batch_size: int = 100,
        priority: int = 0,
        on_publish: Optional[Callable[[str, str], None]] = None,
    ) -> List[str]:
        """
        Submit multiple URLs for scraping.
        
        Args:
            urls: List of URLs to scrape
            batch_size: Number of messages to publish in parallel
            priority: Job priority
            on_publish: Callback(url, job_id) when each URL is published
            
        Returns:
            List of job IDs
        """
        job_ids = []
        futures: List[tuple] = []
        
        for url in urls:
            request = ScrapeRequest(url=url, priority=priority)
            
            future = self._publisher.publish(
                self._topic_path,
                request.to_json().encode("utf-8"),
                priority=str(priority),
            )
            
            futures.append((request, future))
            self._pending_jobs[request.job_id] = request
            
            # Process batch
            if len(futures) >= batch_size:
                for req, fut in futures:
                    try:
                        fut.result()
                        job_ids.append(req.job_id)
                        if on_publish:
                            on_publish(req.url, req.job_id)
                    except Exception as e:
                        logger.error(f"Failed to publish {req.url}: {e}")
                futures = []
        
        # Process remaining
        for req, fut in futures:
            try:
                fut.result()
                job_ids.append(req.job_id)
                if on_publish:
                    on_publish(req.url, req.job_id)
            except Exception as e:
                logger.error(f"Failed to publish {req.url}: {e}")
        
        logger.info(f"Published {len(job_ids)} jobs")
        return job_ids
    
    def submit_from_file(
        self,
        path: str,
        column: Optional[str] = None,
        priority: int = 0,
    ) -> List[str]:
        """
        Submit URLs from a file.
        
        Supports:
        - Text file (one URL per line)
        - CSV (specify column)
        - JSON (list of URLs or objects with 'url' field)
        """
        import csv
        from pathlib import Path
        
        path = Path(path)
        urls = []
        
        with open(path, "r") as f:
            if path.suffix == ".csv":
                reader = csv.DictReader(f)
                col = column or "url"
                for row in reader:
                    if col in row and row[col]:
                        urls.append(row[col].strip())
            
            elif path.suffix == ".json":
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            urls.append(item.strip())
                        elif isinstance(item, dict) and "url" in item:
                            urls.append(item["url"].strip())
            
            else:  # Text file
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
        
        logger.info(f"Loaded {len(urls)} URLs from {path}")
        return self.submit_batch(urls, priority=priority)
    
    def stream_results(
        self,
        timeout: Optional[float] = None,
        max_messages: Optional[int] = None,
    ) -> Iterator[ScrapeResult]:
        """
        Stream results as they complete.
        
        Args:
            timeout: Stop after N seconds
            max_messages: Stop after N messages
            
        Yields:
            ScrapeResult objects
        """
        if not self.results_subscription:
            raise ValueError("results_subscription not configured")
        
        from google.cloud import pubsub_v1
        
        subscriber = pubsub_v1.SubscriberClient()
        subscription_path = subscriber.subscription_path(
            self.project_id, self.results_subscription
        )
        
        count = 0
        start_time = time.time()
        
        def callback(message):
            nonlocal count
            
            try:
                data = json.loads(message.data.decode("utf-8"))
                result = ScrapeResult.from_json(data)
                self._completed_jobs[result.job_id] = result
                
                if result.job_id in self._pending_jobs:
                    del self._pending_jobs[result.job_id]
                
                message.ack()
                count += 1
                
                # This doesn't work with iterator pattern - use pull instead
            except Exception as e:
                logger.error(f"Error processing result: {e}")
                message.nack()
        
        # Use pull for iterator pattern
        while True:
            if timeout and (time.time() - start_time) > timeout:
                break
            if max_messages and count >= max_messages:
                break
            
            response = subscriber.pull(
                request={"subscription": subscription_path, "max_messages": 10},
                timeout=30,
            )
            
            for msg in response.received_messages:
                try:
                    data = json.loads(msg.message.data.decode("utf-8"))
                    result = ScrapeResult.from_json(data)
                    self._completed_jobs[result.job_id] = result
                    
                    subscriber.acknowledge(
                        request={
                            "subscription": subscription_path,
                            "ack_ids": [msg.ack_id],
                        }
                    )
                    
                    count += 1
                    yield result
                    
                except Exception as e:
                    logger.error(f"Error processing result: {e}")
    
    def get_status(self, job_id: str) -> Optional[ScrapeResult]:
        """Get status of a job (if completed)."""
        return self._completed_jobs.get(job_id)
    
    @property
    def pending_count(self) -> int:
        """Number of pending jobs."""
        return len(self._pending_jobs)
    
    @property
    def completed_count(self) -> int:
        """Number of completed jobs."""
        return len(self._completed_jobs)


def publish_urls_cli():
    """CLI for publishing URLs to GCP."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Publish URLs to VideoScraper GCP")
    parser.add_argument("urls", nargs="*", help="URLs to scrape")
    parser.add_argument("-f", "--file", help="File containing URLs")
    parser.add_argument("-p", "--project", required=True, help="GCP project ID")
    parser.add_argument("-t", "--topic", default="scrape-urls", help="Pub/Sub topic")
    parser.add_argument("--priority", type=int, default=0, help="Job priority")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    client = GCPScraperClient(
        project_id=args.project,
        topic_name=args.topic,
    )
    
    if args.file:
        job_ids = client.submit_from_file(args.file, priority=args.priority)
    elif args.urls:
        job_ids = client.submit_batch(args.urls, priority=args.priority)
    else:
        print("Error: Provide URLs or --file")
        return 1
    
    print(f"Submitted {len(job_ids)} jobs")
    return 0


if __name__ == "__main__":
    exit(publish_urls_cli())

