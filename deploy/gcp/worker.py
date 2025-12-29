#!/usr/bin/env python3
"""
GCP Cloud Run Worker for distributed video scraping.

Features:
- Pulls URLs from Pub/Sub
- Uses proxy rotation for anti-ban
- Uploads to GCS
- Ephemeral IPs (new IP each container)
- Auto-scaling based on queue depth
"""

import base64
import json
import logging
import os
import tempfile
from typing import Any, Dict, Optional

from flask import Flask, request
from videoscraper import ScraperConfig, StorageConfig, Scraper, VideoFilter
from videoscraper.proxy import ProxyConfig, ProxyRotator, random_user_agent
from videoscraper.sites import get_scraper_for_url, YouTubeScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Flask app for Cloud Run
app = Flask(__name__)

# Configuration from environment
GCS_BUCKET = os.getenv("GCS_BUCKET", "video-scraper-output")
GCS_PREFIX = os.getenv("GCS_PREFIX", "videos/")
PROXY_PROVIDER = os.getenv("PROXY_PROVIDER", "brightdata")
PROXY_USERNAME = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = os.getenv("PROXY_PORT", "3128")
PROXY_COUNTRY = os.getenv("PROXY_COUNTRY", "us")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
QUALITY = os.getenv("VIDEO_QUALITY", "1080p")


def get_proxy_url() -> Optional[str]:
    """Get proxy URL from environment."""
    # Handle custom/direct proxy (e.g., local ngrok tunnel)
    if PROXY_PROVIDER == "custom" and PROXY_HOST:
        if PROXY_USERNAME and PROXY_PASSWORD:
            proxy_url = f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_HOST}:{PROXY_PORT}"
        else:
            proxy_url = f"http://{PROXY_HOST}:{PROXY_PORT}"
        logger.info(f"Using custom proxy: {PROXY_HOST}:{PROXY_PORT}")
        return proxy_url
    
    if not PROXY_USERNAME or not PROXY_PASSWORD:
        logger.warning("No proxy credentials configured, using direct connection")
        return None
    
    try:
        if PROXY_PROVIDER == "brightdata":
            proxy_config = ProxyConfig.brightdata(
                username=PROXY_USERNAME,
                password=PROXY_PASSWORD,
                country=PROXY_COUNTRY,
            )
        elif PROXY_PROVIDER == "oxylabs":
            proxy_config = ProxyConfig.oxylabs(
                username=PROXY_USERNAME,
                password=PROXY_PASSWORD,
                country=PROXY_COUNTRY,
            )
        elif PROXY_PROVIDER == "smartproxy":
            proxy_config = ProxyConfig.smartproxy(
                username=PROXY_USERNAME,
                password=PROXY_PASSWORD,
                country=PROXY_COUNTRY,
            )
        else:
            proxy_config = ProxyConfig.from_env()
        
        if proxy_config:
            rotator = ProxyRotator(proxy_config)
            return rotator.get_proxy()
    except Exception as e:
        logger.warning(f"Failed to configure proxy: {e}")
    
    return None


def get_scraper_config() -> ScraperConfig:
    """Get scraper configuration with proxy support."""
    config = ScraperConfig()
    
    # Get proxy URL if configured
    proxy_url = get_proxy_url()
    if proxy_url:
        config.proxy_url = proxy_url
    
    # Rotate user agent
    config.user_agent = random_user_agent()
    
    # Conservative rate limiting (proxy handles multiple IPs)
    config.rate_limit_per_second = 2.0
    config.max_retries = MAX_RETRIES
    
    # Enable resume for large files
    config.enable_resume = True
    config.chunk_size_bytes = 16 * 1024 * 1024  # 16MB chunks
    
    return config


def upload_to_gcs(local_path: str, gcs_key: str) -> str:
    """Upload file to GCS and return public URL."""
    from google.cloud import storage
    
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(f"{GCS_PREFIX}{gcs_key}")
    
    blob.upload_from_filename(local_path)
    logger.info(f"Uploaded to gs://{GCS_BUCKET}/{GCS_PREFIX}{gcs_key}")
    
    return f"gs://{GCS_BUCKET}/{GCS_PREFIX}{gcs_key}"


def process_url(url: str, job_id: str) -> Dict[str, Any]:
    """
    Process a single URL: extract, download, upload to GCS.
    
    Args:
        url: URL to scrape
        job_id: Unique job identifier
        
    Returns:
        Result dictionary with status and metadata
    """
    logger.info(f"Processing job {job_id}: {url}")
    
    result = {
        "job_id": job_id,
        "url": url,
        "status": "pending",
        "gcs_path": None,
        "size_bytes": None,
        "error": None,
    }
    
    try:
        config = get_scraper_config()
        proxy_url = get_proxy_url()
        user_agent = random_user_agent()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Determine scraper type
            if "youtube.com" in url or "youtu.be" in url:
                scraper = YouTubeScraper(
                    output_dir=tmpdir,
                    quality=QUALITY,
                    format="mp4",
                    proxy=proxy_url,
                    user_agent=user_agent,
                )
                scrape_result = scraper.download(url)
            else:
                scraper = Scraper(output_dir=tmpdir, config=config)
                scrape_result = scraper.scrape(url)
            
            if not scrape_result.success:
                result["status"] = "failed"
                result["error"] = scrape_result.error
                return result
            
            # Upload to GCS
            local_path = scrape_result.output_path
            if local_path and os.path.exists(local_path):
                file_name = os.path.basename(local_path)
                gcs_key = f"{job_id}/{file_name}"
                gcs_path = upload_to_gcs(local_path, gcs_key)
                
                result["status"] = "success"
                result["gcs_path"] = gcs_path
                result["size_bytes"] = os.path.getsize(local_path)
                
                if scrape_result.video_info:
                    result["title"] = scrape_result.video_info.title
                    result["duration"] = scrape_result.video_info.duration_secs
            else:
                result["status"] = "failed"
                result["error"] = "No output file generated"
        
    except Exception as e:
        logger.exception(f"Error processing {url}")
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


@app.route("/", methods=["POST"])
def handle_pubsub():
    """
    Handle Pub/Sub push messages.
    
    Message format:
    {
        "url": "https://...",
        "job_id": "uuid",
        "options": {...}
    }
    """
    envelope = request.get_json()
    
    if not envelope:
        return "Bad Request: no Pub/Sub message received", 400
    
    if not isinstance(envelope, dict) or "message" not in envelope:
        return "Bad Request: invalid Pub/Sub message format", 400
    
    pubsub_message = envelope["message"]
    
    if isinstance(pubsub_message, dict) and "data" in pubsub_message:
        data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
        message = json.loads(data)
    else:
        return "Bad Request: no data in message", 400
    
    url = message.get("url")
    job_id = message.get("job_id", pubsub_message.get("messageId", "unknown"))
    
    if not url:
        return "Bad Request: no URL in message", 400
    
    result = process_url(url, job_id)
    
    # Log result (could also publish to result topic)
    logger.info(f"Job {job_id} result: {result['status']}")
    
    # Return 200 to acknowledge message (even for failures)
    # Pub/Sub will retry on non-200 responses
    return json.dumps(result), 200


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return "OK", 200


@app.route("/scrape", methods=["POST"])
def scrape_direct():
    """
    Direct scrape endpoint for testing.
    
    POST body:
    {
        "url": "https://...",
        "job_id": "optional-id"
    }
    """
    data = request.get_json()
    
    if not data or "url" not in data:
        return {"error": "Missing 'url' in request body"}, 400
    
    url = data["url"]
    job_id = data.get("job_id", f"direct-{hash(url) % 10000}")
    
    result = process_url(url, job_id)
    
    status_code = 200 if result["status"] == "success" else 500
    return json.dumps(result), status_code


@app.route("/crawl", methods=["POST"])
def crawl():
    """
    Crawl YouTube starting from a seed video.
    
    Discovers related videos through graph traversal and optionally downloads them.
    
    POST body:
    {
        "seed_url": "https://www.youtube.com/watch?v=...",
        "max_videos": 10,          // Max videos to discover (default: 10, max: 50)
        "download": false,          // Whether to download videos (default: false)
        "job_id": "optional-id"
    }
    
    Returns:
    {
        "job_id": "...",
        "status": "success",
        "videos_discovered": 10,
        "videos_downloaded": 5,
        "discovered": [
            {"video_id": "...", "title": "...", "url": "...", "gcs_path": "..."},
            ...
        ],
        "stats": {...}
    }
    """
    from videoscraper.crawler import YouTubeCrawler, VideoNode
    
    data = request.get_json()
    
    if not data or "seed_url" not in data:
        return {"error": "Missing 'seed_url' in request body"}, 400
    
    seed_url = data["seed_url"]
    max_videos = min(int(data.get("max_videos", 10)), 50)  # Cap at 50 for Cloud Run timeout
    do_download = data.get("download", False)
    job_id = data.get("job_id", f"crawl-{hash(seed_url) % 10000}")
    
    logger.info(f"Starting crawl job {job_id} from {seed_url}, max_videos={max_videos}, download={do_download}")
    
    result = {
        "job_id": job_id,
        "seed_url": seed_url,
        "status": "pending",
        "videos_discovered": 0,
        "videos_downloaded": 0,
        "discovered": [],
        "downloaded": [],
        "stats": {},
        "error": None,
    }
    
    try:
        # Get proxy settings
        proxy_url = get_proxy_url()
        user_agent = random_user_agent()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create crawler (discovery only, no internal download)
            crawler = YouTubeCrawler(
                max_videos=max_videos,
                max_depth=10,
                num_workers=2,  # Keep low for Cloud Run
                download=False,  # Don't use internal download (no proxy support)
                output_dir=tmpdir,
                random_walk_prob=0.8,
                rate_limit_per_worker=0.5,  # Conservative rate limit
            )
            
            # Add seed
            if not crawler.add_seed(seed_url):
                result["status"] = "failed"
                result["error"] = "Invalid seed URL"
                return json.dumps(result), 400
            
            # Run crawler (discovery phase)
            stats = crawler.run()
            
            # Collect discovered videos
            for node in crawler.discovered_videos:
                result["discovered"].append({
                    "video_id": node.video_id,
                    "title": node.title,
                    "url": node.url,
                    "channel": node.channel,
                    "duration": node.duration,
                    "view_count": node.view_count,
                    "depth": node.depth,
                })
            
            # Download videos with proxy support (separate from crawler)
            if do_download and crawler.discovered_videos:
                logger.info(f"Downloading {len(crawler.discovered_videos)} discovered videos with proxy")
                
                # Create proxy-enabled YouTube scraper
                yt_scraper = YouTubeScraper(
                    output_dir=tmpdir,
                    quality=QUALITY,
                    format="mp4",
                    proxy=proxy_url,
                    user_agent=user_agent,
                )
                
                download_count = 0
                bytes_downloaded = 0
                
                for node in crawler.discovered_videos:
                    try:
                        logger.info(f"Downloading {node.video_id}...")
                        scrape_result = yt_scraper.download(node.url)
                        
                        if scrape_result.success and scrape_result.output_path:
                            local_path = scrape_result.output_path
                            if os.path.exists(local_path):
                                file_size = os.path.getsize(local_path)
                                file_name = os.path.basename(local_path)
                                gcs_key = f"{job_id}/{node.video_id}/{file_name}"
                                gcs_path = upload_to_gcs(local_path, gcs_key)
                                
                                result["downloaded"].append({
                                    "video_id": node.video_id,
                                    "title": node.title,
                                    "gcs_path": gcs_path,
                                    "size_bytes": file_size,
                                })
                                download_count += 1
                                bytes_downloaded += file_size
                                logger.info(f"Downloaded and uploaded {node.video_id}")
                        else:
                            logger.warning(f"Download failed for {node.video_id}: {scrape_result.error}")
                            
                    except Exception as e:
                        logger.error(f"Failed to download {node.video_id}: {e}")
                
                stats.videos_downloaded = download_count
                stats.bytes_downloaded = bytes_downloaded
            
            result["status"] = "success"
            result["videos_discovered"] = stats.videos_discovered
            result["videos_downloaded"] = stats.videos_downloaded
            result["stats"] = {
                "elapsed_seconds": stats.elapsed_seconds,
                "videos_per_second": stats.videos_per_second,
                "errors": stats.errors,
                "bytes_downloaded": stats.bytes_downloaded,
            }
            
    except Exception as e:
        logger.exception(f"Crawl error: {e}")
        result["status"] = "error"
        result["error"] = str(e)
    
    status_code = 200 if result["status"] == "success" else 500
    return json.dumps(result), status_code


if __name__ == "__main__":
    # For local development
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)

