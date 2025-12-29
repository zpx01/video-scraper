# VideoScraper GCP Demo Guide

This guide walks you through deploying VideoScraper on Google Cloud Platform for scalable video scraping. By the end, you'll have a working distributed system that can scrape and crawl YouTube videos at scale.

## 📋 Prerequisites

Before starting, ensure you have:

1. **Google Cloud Account** with billing enabled
2. **gcloud CLI** installed ([Install Guide](https://cloud.google.com/sdk/docs/install))
3. **Python 3.8+** and **Rust** installed
4. **ngrok** (for local residential proxy testing)
5. VideoScraper built locally (`make dev`)

Verify your setup:

```bash
# Check gcloud
gcloud --version

# Check Rust
rustc --version

# Check Python
python --version

# Check ngrok (optional, for residential IP testing)
ngrok --version
```

## 🚀 Quick Start (5 minutes)

### Step 1: Set Up GCP Project

```bash
# Set your project ID
export GCP_PROJECT_ID="your-project-id"

# Authenticate
gcloud auth login

# Set project
gcloud config set project $GCP_PROJECT_ID

# Enable required APIs
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    storage.googleapis.com
```

### Step 2: Build and Deploy

```bash
# Build the Docker image
gcloud builds submit \
    --tag gcr.io/$GCP_PROJECT_ID/videoscraper-demo \
    --timeout=30m \
    .

# Create GCS bucket for videos
gcloud storage buckets create gs://${GCP_PROJECT_ID}-videos \
    --location=us-central1 \
    --uniform-bucket-level-access

# Deploy to Cloud Run
gcloud run deploy videoscraper-demo \
    --image gcr.io/$GCP_PROJECT_ID/videoscraper-demo \
    --region us-central1 \
    --memory 2Gi \
    --cpu 2 \
    --timeout 600 \
    --allow-unauthenticated \
    --set-env-vars "GCS_BUCKET=${GCP_PROJECT_ID}-videos,YT_DLP_JS_RUNTIMES=deno"
```

### Step 3: Get Service URL

```bash
export SERVICE_URL=$(gcloud run services describe videoscraper-demo \
    --region us-central1 \
    --format="value(status.url)")

echo "Service URL: $SERVICE_URL"
```

## 🏠 Local Residential Proxy Setup

YouTube blocks datacenter IPs. To test YouTube scraping, expose your local residential IP:

### Step 1: Start Local Proxy

```bash
# Terminal 1: Start the proxy server
make local-proxy

# Or directly:
python deploy/proxy/simple_proxy_server.py
```

### Step 2: Expose via ngrok

```bash
# Terminal 2: Expose the proxy
ngrok tcp 8888
```

You'll see output like:
```
Forwarding  tcp://0.tcp.ngrok.io:12345 -> localhost:8888
```

### Step 3: Update Cloud Run with Proxy

```bash
# Replace with YOUR ngrok host and port
export NGROK_HOST="0.tcp.ngrok.io"
export NGROK_PORT="12345"

gcloud run services update videoscraper-demo \
    --set-env-vars "GCS_BUCKET=${GCP_PROJECT_ID}-videos,YT_DLP_JS_RUNTIMES=deno,PROXY_PROVIDER=custom,PROXY_HOST=$NGROK_HOST,PROXY_PORT=$NGROK_PORT,PROXY_USERNAME=videoscraper,PROXY_PASSWORD=testpass123" \
    --region us-central1
```

## 📡 API Endpoints

### Health Check

```bash
curl $SERVICE_URL/health
# Returns: OK
```

### Single Video Scrape

Download a single YouTube video:

```bash
curl -X POST $SERVICE_URL/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    "job_id": "my-job-001"
  }'
```

**Response:**
```json
{
  "job_id": "my-job-001",
  "url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
  "status": "success",
  "gcs_path": "gs://bucket/videos/my-job-001/video.mp4",
  "size_bytes": 3863745
}
```

### YouTube Crawling (Discovery Only)

Discover related videos through graph traversal:

```bash
curl -X POST $SERVICE_URL/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "seed_url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    "max_videos": 10,
    "download": false,
    "job_id": "crawl-001"
  }'
```

**Response:**
```json
{
  "job_id": "crawl-001",
  "status": "success",
  "videos_discovered": 10,
  "discovered": [
    {"video_id": "abc123", "title": "Video 1", "depth": 0},
    {"video_id": "def456", "title": "Video 2", "depth": 1},
    ...
  ],
  "stats": {
    "elapsed_seconds": 25.5,
    "videos_per_second": 0.39
  }
}
```

### Crawl with Download

Discover related videos AND download them to GCS:

```bash
curl -X POST $SERVICE_URL/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "seed_url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    "max_videos": 5,
    "download": true,
    "job_id": "crawl-download-001"
  }'
```

**Response:**
```json
{
  "job_id": "crawl-download-001",
  "status": "success",
  "videos_discovered": 5,
  "videos_downloaded": 5,
  "discovered": [...],
  "downloaded": [
    {
      "video_id": "abc123",
      "title": "Video Title",
      "gcs_path": "gs://bucket/videos/crawl-download-001/abc123/video.mp4",
      "size_bytes": 5242880
    },
    ...
  ],
  "stats": {
    "elapsed_seconds": 120.5,
    "bytes_downloaded": 52428800
  }
}
```

## 🔧 Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GCS_BUCKET` | GCS bucket for output | (required) |
| `GCS_PREFIX` | Key prefix in bucket | `videos/` |
| `PROXY_PROVIDER` | Proxy provider (`brightdata`, `oxylabs`, `smartproxy`, `custom`) | - |
| `PROXY_HOST` | Proxy hostname (for `custom` provider) | - |
| `PROXY_PORT` | Proxy port | `3128` |
| `PROXY_USERNAME` | Proxy username | - |
| `PROXY_PASSWORD` | Proxy password | - |
| `PROXY_COUNTRY` | Target country for geo-targeting | `us` |
| `VIDEO_QUALITY` | Download quality (`720p`, `1080p`, `best`) | `1080p` |
| `MAX_RETRIES` | Retry attempts | `3` |
| `YT_DLP_JS_RUNTIMES` | JS runtime for yt-dlp | `deno` |

### Crawl Parameters

| Parameter | Description | Default | Max |
|-----------|-------------|---------|-----|
| `seed_url` | Starting YouTube video URL | (required) | - |
| `max_videos` | Max videos to discover | 10 | 50 |
| `download` | Download discovered videos | false | - |
| `job_id` | Custom job identifier | auto-generated | - |

## 🔐 Production Proxy Setup

For production use, configure a commercial proxy provider:

### Bright Data

```bash
gcloud run services update videoscraper-demo \
    --set-env-vars "PROXY_PROVIDER=brightdata,PROXY_USERNAME=YOUR_USER,PROXY_PASSWORD=YOUR_PASS,PROXY_COUNTRY=us" \
    --region us-central1
```

### Oxylabs

```bash
gcloud run services update videoscraper-demo \
    --set-env-vars "PROXY_PROVIDER=oxylabs,PROXY_USERNAME=YOUR_USER,PROXY_PASSWORD=YOUR_PASS,PROXY_COUNTRY=us" \
    --region us-central1
```

### SmartProxy

```bash
gcloud run services update videoscraper-demo \
    --set-env-vars "PROXY_PROVIDER=smartproxy,PROXY_USERNAME=YOUR_USER,PROXY_PASSWORD=YOUR_PASS,PROXY_COUNTRY=us" \
    --region us-central1
```

## 📊 Verify Downloads

Check your GCS bucket for downloaded videos:

```bash
# List all downloads
gcloud storage ls -r gs://${GCP_PROJECT_ID}-videos/videos/

# Download a video locally
gcloud storage cp "gs://${GCP_PROJECT_ID}-videos/videos/my-job-001/*.mp4" ./
```

## 📈 Scaling

### Increase Resources

```bash
# More memory for large videos
gcloud run services update videoscraper-demo \
    --memory 4Gi \
    --cpu 4 \
    --region us-central1

# More instances for parallelism
gcloud run services update videoscraper-demo \
    --max-instances 20 \
    --region us-central1

# Longer timeout for crawl+download jobs
gcloud run services update videoscraper-demo \
    --timeout 900 \
    --region us-central1
```

### Performance Expectations

| Operation | Typical Time | Notes |
|-----------|--------------|-------|
| Single video scrape | 5-30s | Depends on video size |
| Crawl 10 videos (no download) | 20-60s | Discovery only |
| Crawl 5 videos + download | 60-180s | Includes upload to GCS |

## 🛑 Cleanup

Remove all resources when done:

```bash
# Delete Cloud Run service
gcloud run services delete videoscraper-demo --region us-central1 --quiet

# Delete GCS bucket (WARNING: deletes all videos!)
gcloud storage rm -r gs://${GCP_PROJECT_ID}-videos

# Delete container images
gcloud container images delete gcr.io/$GCP_PROJECT_ID/videoscraper-demo --quiet
```

## 🐛 Troubleshooting

### "Sign in to confirm you're not a bot"

YouTube is blocking datacenter IPs. Use a residential proxy:
1. Set up local proxy with ngrok (see above)
2. Or configure a commercial proxy provider

### "Service Unavailable"

Check Cloud Run logs:
```bash
gcloud run services logs read videoscraper-demo --region us-central1 --limit 50
```

### Timeout errors

Increase the Cloud Run timeout:
```bash
gcloud run services update videoscraper-demo --timeout 900 --region us-central1
```

### Out of memory

Increase memory allocation:
```bash
gcloud run services update videoscraper-demo --memory 4Gi --region us-central1
```

### GCS upload fails

Check bucket exists and has correct permissions:
```bash
gcloud storage buckets describe gs://${GCP_PROJECT_ID}-videos
```

## 📚 Related Documentation

- [Main README](../README.md) - Full VideoScraper documentation
- [Proxy Setup](../deploy/proxy/) - Self-hosted proxy options
- [Terraform Deployment](../deploy/gcp/terraform/) - Infrastructure as Code

## 🎯 Next Steps

1. **Local Development**: Run `make demo` for local testing
2. **Batch Processing**: Use Pub/Sub for async job processing  
3. **Multi-Region**: Deploy to multiple regions for geo-distribution
4. **Monitoring**: Set up Cloud Monitoring dashboards
