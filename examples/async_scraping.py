#!/usr/bin/env python3
"""
Async scraping example using asyncio.

This example shows how to use the async API for non-blocking
video scraping in async applications.
"""

import asyncio
from videoscraper.scraper import AsyncScraper, ScrapeResult


async def scrape_with_progress():
    """Scrape multiple URLs with progress reporting."""
    scraper = AsyncScraper(output_dir="./async_downloads")
    
    urls = [
        "https://example.com/video1",
        "https://example.com/video2",
        "https://example.com/video3",
        "https://example.com/video4",
        "https://example.com/video5",
    ]
    
    print(f"Starting async scrape of {len(urls)} URLs...")
    
    # Scrape all URLs concurrently
    results = await scraper.scrape_many(urls, concurrency=4)
    
    # Report results
    for result in results:
        status = "✓" if result.success else "✗"
        print(f"{status} {result.url}")
    
    return results


async def scrape_with_timeout():
    """Scrape with a timeout."""
    scraper = AsyncScraper(output_dir="./async_downloads")
    
    try:
        result = await asyncio.wait_for(
            scraper.scrape("https://example.com/large-video"),
            timeout=60.0,  # 1 minute timeout
        )
        print(f"Download complete: {result.output_path}")
    except asyncio.TimeoutError:
        print("Download timed out")


async def scrape_with_semaphore():
    """Control concurrency with a semaphore."""
    scraper = AsyncScraper(output_dir="./async_downloads")
    semaphore = asyncio.Semaphore(5)  # Max 5 concurrent downloads
    
    async def download_with_limit(url: str) -> ScrapeResult:
        async with semaphore:
            print(f"Starting: {url}")
            result = await scraper.scrape(url)
            print(f"Finished: {url} ({'success' if result.success else 'failed'})")
            return result
    
    urls = [f"https://example.com/video{i}" for i in range(20)]
    
    # All start immediately but semaphore limits concurrent execution
    tasks = [download_with_limit(url) for url in urls]
    results = await asyncio.gather(*tasks)
    
    success_count = sum(1 for r in results if r.success)
    print(f"\nCompleted: {success_count}/{len(results)} succeeded")


async def producer_consumer_pattern():
    """
    Producer-consumer pattern for streaming URL processing.
    
    Useful for processing URLs from a live feed or queue.
    """
    scraper = AsyncScraper(output_dir="./async_downloads")
    
    # URL queue
    url_queue: asyncio.Queue = asyncio.Queue()
    result_queue: asyncio.Queue = asyncio.Queue()
    
    async def producer():
        """Simulate producing URLs (e.g., from a database or API)."""
        for i in range(100):
            url = f"https://example.com/video{i}"
            await url_queue.put(url)
            await asyncio.sleep(0.1)  # Simulate delay
        
        # Signal completion
        for _ in range(5):  # Number of workers
            await url_queue.put(None)
    
    async def worker(worker_id: int):
        """Worker that consumes URLs and downloads."""
        while True:
            url = await url_queue.get()
            if url is None:
                break
            
            result = await scraper.scrape(url)
            await result_queue.put(result)
            
            print(f"Worker {worker_id}: {url} - {'✓' if result.success else '✗'}")
    
    async def result_collector():
        """Collect and aggregate results."""
        results = []
        completed = 0
        
        while completed < 100:
            result = await result_queue.get()
            results.append(result)
            completed += 1
            
            if completed % 10 == 0:
                success = sum(1 for r in results if r.success)
                print(f"Progress: {completed}/100 ({success} successful)")
        
        return results
    
    # Run producer, workers, and collector
    await asyncio.gather(
        producer(),
        *[worker(i) for i in range(5)],
        result_collector(),
    )


async def main():
    """Run all async examples."""
    print("=== Basic Async Scraping ===")
    await scrape_with_progress()
    
    print("\n=== With Timeout ===")
    await scrape_with_timeout()
    
    print("\n=== With Semaphore ===")
    await scrape_with_semaphore()
    
    print("\n=== Producer-Consumer Pattern ===")
    await producer_consumer_pattern()


if __name__ == "__main__":
    asyncio.run(main())

