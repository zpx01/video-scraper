# VideoScraper GCP Deployment

Deploy VideoScraper to Google Cloud Run for scalable YouTube scraping.

## Quick Start

```bash
# 1. Set project
export PROJECT_ID="your-project-id"
gcloud config set project $PROJECT_ID

# 2. Enable APIs
gcloud services enable run.googleapis.com cloudbuild.googleapis.com storage.googleapis.com

# 3. Create bucket
gcloud storage buckets create gs://${PROJECT_ID}-videos --location=us-central1

# 4. Build & Deploy
gcloud builds submit --tag gcr.io/$PROJECT_ID/videoscraper-demo --timeout=30m .
gcloud run deploy videoscraper-demo \
    --image gcr.io/$PROJECT_ID/videoscraper-demo \
    --region us-central1 \
    --memory 2Gi \
    --timeout 600 \
    --allow-unauthenticated \
    --set-env-vars "GCS_BUCKET=${PROJECT_ID}-videos,YT_DLP_JS_RUNTIMES=deno"
```

## API Reference

### Health Check
```bash
curl https://YOUR-SERVICE.run.app/health
```

### Scrape Single Video
```bash
curl -X POST https://YOUR-SERVICE.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=VIDEO_ID"}'
```

### Crawl Related Videos
```bash
curl -X POST https://YOUR-SERVICE.run.app/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "seed_url": "https://youtube.com/watch?v=VIDEO_ID",
    "max_videos": 10,
    "download": true
  }'
```

## Residential Proxy Setup

YouTube blocks datacenter IPs. Use your local IP:

```bash
# Terminal 1: Start proxy
python ../proxy/simple_proxy_server.py

# Terminal 2: Expose via ngrok
ngrok tcp 8888

# Terminal 3: Update Cloud Run
gcloud run services update videoscraper-demo \
    --set-env-vars "PROXY_PROVIDER=custom,PROXY_HOST=0.tcp.ngrok.io,PROXY_PORT=12345,PROXY_USERNAME=videoscraper,PROXY_PASSWORD=testpass123" \
    --region us-central1
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GCS_BUCKET` | Output bucket name | Yes |
| `PROXY_PROVIDER` | `brightdata`, `oxylabs`, `smartproxy`, or `custom` | No |
| `PROXY_HOST` | Proxy hostname (for `custom`) | No |
| `PROXY_PORT` | Proxy port | No |
| `PROXY_USERNAME` | Proxy auth username | No |
| `PROXY_PASSWORD` | Proxy auth password | No |
| `VIDEO_QUALITY` | `720p`, `1080p`, `best` | No |

## Files

| File | Description |
|------|-------------|
| `Dockerfile` | Multi-stage build with Rust + Python + deno |
| `worker.py` | Flask app with /scrape and /crawl endpoints |
| `requirements.txt` | Python dependencies |
| `terraform/` | Infrastructure as Code |

## Cleanup

```bash
gcloud run services delete videoscraper-demo --region us-central1 --quiet
gcloud storage rm -r gs://${PROJECT_ID}-videos
gcloud container images delete gcr.io/$PROJECT_ID/videoscraper-demo --quiet
```

## Full Documentation

See [GCP Demo Guide](../../demo/GCP_DEMO_GUIDE.md) for complete instructions.
