# VideoScraper

**High-performance video content scraping infrastructure built with Rust and Python.** 
**Built with Claude :)**

VideoScraper is designed for large-scale video collection at petabyte scale. The core infrastructure is written in Rust for maximum performance, with easy-to-use Python APIs for building scraping pipelines.

## Features

- ⚡ **High Performance**: Rust core with async I/O for maximum throughput
- 🔄 **Resumable Downloads**: Automatic resume for interrupted downloads with chunked transfer
- 🚦 **Rate Limiting**: Built-in per-domain rate limiting to respect server limits
- 📦 **Multiple Storage Backends**: Local filesystem, AWS S3, Google Cloud Storage
- 🔍 **Video Extraction**: Automatic extraction of video URLs from web pages
- 🎬 **Site-Specific Scrapers**: Optimized scrapers for YouTube, Vimeo, Twitter, TikTok
- 🔧 **Pipeline Processing**: Orchestrate complex scraping workflows
- 📊 **Progress Tracking**: Real-time progress and statistics
- 💾 **Checkpointing**: Resume batch jobs from interruption

## Installation

### From Source

```bash
# Install Rust (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Clone and build
git clone https://github.com/videoscraper/videoscraper
cd videoscraper

# Install with maturin
pip install maturin
maturin develop --release

# Or build wheel
maturin build --release
pip install target/wheels/videoscraper-*.whl
```

### Optional: yt-dlp for YouTube support

```bash
pip install yt-dlp
```

## Quick Start

### Simple Download

```python
from videoscraper import Scraper

# Create a scraper
scraper = Scraper(output_dir="./videos")

# Download a video
result = scraper.scrape("https://example.com/video.html")
print(f"Downloaded: {result.output_path}")
```

### YouTube Downloads

```python
from videoscraper import YouTubeScraper

scraper = YouTubeScraper(
    output_dir="./youtube",
    quality="1080p",
    format="mp4",
)

# Download a video
result = scraper.download("https://youtube.com/watch?v=VIDEO_ID")

# Download a playlist
results = scraper.download_playlist(
    "https://youtube.com/playlist?list=PLAYLIST_ID",
    max_videos=10,
)
```

### Batch Processing

```python
from videoscraper import BatchScraper, BatchConfig

config = BatchConfig(
    max_concurrent=64,
    output_dir="./videos",
    checkpoint_file="./checkpoint.json",  # Resume from interruption
)

scraper = BatchScraper(config)

# Load URLs from file
scraper.add_from_file("urls.txt")

# Or add URLs directly
scraper.add_urls([
    "https://example.com/video1",
    "https://example.com/video2",
])

# Run the batch
results = scraper.run()

# Export results
scraper.export_results("results.csv")

# Retry failed downloads
scraper.retry_failed()
```

### Pipeline API

For complex workflows with custom processing:

```python
from videoscraper import Pipeline, ScraperConfig, VideoFilter

# Configure for high performance
config = ScraperConfig.high_performance()
config.max_concurrent_downloads = 128
config.rate_limit_per_second = 50.0

# Create pipeline with filter
pipeline = Pipeline(config)

# Add URLs
pipeline.add_urls([
    "https://example.com/page1",
    "https://example.com/page2",
])

# Run with concurrency and filtering
filter = VideoFilter.hd()  # Only 720p+
pipeline.run(concurrency=32, filter=filter)

# Check statistics
stats = pipeline.stats()
print(f"Downloaded: {stats.completed_jobs}")
print(f"Total bytes: {stats.total_bytes_downloaded}")

# Get job details
for job in pipeline.jobs():
    print(f"{job.id}: {job.status} - {job.output_path}")
```

### Cloud Storage

```python
from videoscraper import Pipeline, StorageConfig

# S3 storage
storage = StorageConfig.s3(
    bucket="my-video-bucket",
    region="us-west-2",
    key_prefix="scraped-videos/",
)

# GCS storage
storage = StorageConfig.gcs(
    bucket="my-gcs-bucket",
    project="my-project",
)

# Use with pipeline
pipeline = Pipeline(storage_config=storage)
```

## CLI Usage

```bash
# Download a video
videoscraper download "https://youtube.com/watch?v=VIDEO_ID"

# Download with options
videoscraper download "https://youtube.com/watch?v=VIDEO_ID" \
    -o ./videos \
    -q 1080p \
    -f mp4

# Extract video URLs (no download)
videoscraper extract "https://example.com/page"

# Batch download from file
videoscraper batch urls.txt \
    -o ./videos \
    -c 32 \
    --checkpoint checkpoint.json \
    --results results.csv

# Get video info
videoscraper info "https://youtube.com/watch?v=VIDEO_ID" --json
```

## Configuration

### ScraperConfig Options

```python
from videoscraper import ScraperConfig

config = ScraperConfig()

# Concurrency
config.max_concurrent_downloads = 32  # Simultaneous downloads
config.max_requests_per_domain = 8    # Per-domain limit

# Downloads
config.chunk_size_bytes = 8 * 1024 * 1024  # 8MB chunks
config.enable_resume = True                 # Resume interrupted downloads
config.request_timeout_secs = 300           # 5 minute timeout

# Retries
config.max_retries = 5
config.retry_delay_ms = 1000

# Rate limiting
config.rate_limit_per_second = 2.0
config.respect_robots_txt = True

# Filtering
config.allowed_formats = ["mp4", "webm", "mkv"]
config.max_file_size_bytes = 10 * 1024**3  # 10GB max
```

### Presets

```python
# High performance (aggressive)
config = ScraperConfig.high_performance()

# Conservative (respectful)
config = ScraperConfig.conservative()
```

### VideoFilter Options

```python
from videoscraper import VideoFilter

# Custom filter
filter = VideoFilter()
filter.min_height = 720          # Minimum 720p
filter.max_height = 1080         # Maximum 1080p
filter.allowed_formats = ["mp4"]
filter.min_duration_secs = 60    # At least 1 minute
filter.max_size_bytes = 1024**3  # Max 1GB

# Presets
filter = VideoFilter.hd()   # 720p+
filter = VideoFilter.uhd()  # 4K
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Python API Layer                        │
│  ┌─────────┐  ┌────────────┐  ┌───────────┐  ┌───────────┐  │
│  │ Scraper │  │BatchScraper│  │ Pipeline  │  │  Sites    │  │
│  └────┬────┘  └─────┬──────┘  └─────┬─────┘  └─────┬─────┘  │
└───────┼─────────────┼───────────────┼──────────────┼────────┘
        │             │               │              │
┌───────┴─────────────┴───────────────┴──────────────┴────────┐
│                   Rust Core (PyO3)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  HttpClient  │  │DownloadMgr  │  │  Extractor   │        │
│  │ • Pooling    │  │ • Chunked   │  │ • HTML Parse │        │
│  │ • Rate Limit │  │ • Resume    │  │ • Regex      │        │
│  │ • Retry      │  │ • Parallel  │  │ • DOM        │        │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Storage    │  │   Pipeline   │  │    Config    │       │
│  │ • Local      │  │ • Queue      │  │ • Validation │       │
│  │ • S3         │  │ • Workers    │  │ • Presets    │       │
│  │ • GCS        │  │ • Stats      │  │ • Serialize  │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Performance

VideoScraper is optimized for petabyte-scale collection:

| Metric | Value |
|--------|-------|
| Concurrent downloads | Up to 1000+ |
| Download speed | Limited by bandwidth |
| Resume capability | Yes, per-chunk |
| Memory usage | ~50MB base + streaming |
| CPU usage | Minimal (async I/O) |

### Scaling Tips

1. **Increase concurrency** for high-bandwidth connections:
   ```python
   config.max_concurrent_downloads = 256
   ```

2. **Use chunked downloads** for large files:
   ```python
   config.chunk_size_bytes = 32 * 1024 * 1024  # 32MB chunks
   ```

3. **Enable S3/GCS storage** for distributed collection:
   ```python
   storage = StorageConfig.s3("bucket", region="us-east-1")
   ```

4. **Use checkpointing** for long-running jobs:
   ```python
   config = BatchConfig(checkpoint_file="checkpoint.json")
   ```

## GCP Deployment

Deploy VideoScraper to Google Cloud Run for scalable video scraping:

### Quick Deploy

```bash
# Set your project
export GCP_PROJECT_ID="your-project-id"

# Build and deploy
gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/videoscraper-demo .
gcloud run deploy videoscraper-demo \
    --image gcr.io/$GCP_PROJECT_ID/videoscraper-demo \
    --region us-central1 \
    --memory 2Gi \
    --allow-unauthenticated \
    --set-env-vars "GCS_BUCKET=${GCP_PROJECT_ID}-videos"
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/scrape` | POST | Download a single video |
| `/crawl` | POST | Discover and download related videos |

### Example: Scrape a Video

```bash
curl -X POST https://your-service.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=VIDEO_ID"}'
```

### Example: Crawl Related Videos

```bash
curl -X POST https://your-service.run.app/crawl \
  -H "Content-Type: application/json" \
  -d '{"seed_url": "https://youtube.com/watch?v=VIDEO_ID", "max_videos": 10, "download": true}'
```

### Local Residential Proxy

YouTube blocks datacenter IPs. Use your home IP for testing:

```bash
# Terminal 1: Start local proxy
make local-proxy

# Terminal 2: Expose via ngrok
ngrok tcp 8888

# Update Cloud Run with ngrok URL
gcloud run services update videoscraper-demo \
    --set-env-vars "PROXY_PROVIDER=custom,PROXY_HOST=0.tcp.ngrok.io,PROXY_PORT=12345,PROXY_USERNAME=videoscraper,PROXY_PASSWORD=testpass123"
```

See [GCP Demo Guide](demo/GCP_DEMO_GUIDE.md) for full deployment instructions.

## License

MIT License - see LICENSE for details.

