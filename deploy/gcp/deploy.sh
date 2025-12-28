#!/bin/bash
set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-your-project-id}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="videoscraper-worker"
GCS_BUCKET="${GCS_BUCKET:-videoscraper-output-${PROJECT_ID}}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🚀 Deploying VideoScraper to GCP...${NC}"

# Check prerequisites
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}❌ gcloud CLI not found. Install it from https://cloud.google.com/sdk/docs/install${NC}"
    exit 1
fi

# Set project
echo -e "${YELLOW}📋 Setting project to ${PROJECT_ID}...${NC}"
gcloud config set project "${PROJECT_ID}"

# Enable required APIs
echo -e "${YELLOW}🔧 Enabling required APIs...${NC}"
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    pubsub.googleapis.com \
    secretmanager.googleapis.com \
    storage.googleapis.com \
    cloudscheduler.googleapis.com

# Create GCS bucket for output
echo -e "${YELLOW}🪣 Creating GCS bucket...${NC}"
gsutil mb -l "${REGION}" "gs://${GCS_BUCKET}" 2>/dev/null || echo "Bucket already exists"

# Create Pub/Sub topic for URL distribution
echo -e "${YELLOW}📬 Creating Pub/Sub topic...${NC}"
gcloud pubsub topics create scrape-urls 2>/dev/null || echo "Topic already exists"

# Create dead letter topic for failed messages
gcloud pubsub topics create scrape-urls-deadletter 2>/dev/null || echo "Dead letter topic already exists"

# Store proxy credentials in Secret Manager (if provided)
if [ -n "${PROXY_USERNAME}" ] && [ -n "${PROXY_PASSWORD}" ]; then
    echo -e "${YELLOW}🔐 Storing proxy credentials in Secret Manager...${NC}"
    echo -n "${PROXY_USERNAME}" | gcloud secrets create proxy-username --data-file=- 2>/dev/null || \
        echo -n "${PROXY_USERNAME}" | gcloud secrets versions add proxy-username --data-file=-
    echo -n "${PROXY_PASSWORD}" | gcloud secrets create proxy-password --data-file=- 2>/dev/null || \
        echo -n "${PROXY_PASSWORD}" | gcloud secrets versions add proxy-password --data-file=-
fi

# Build and push Docker image
echo -e "${YELLOW}🐳 Building Docker image...${NC}"
cd "$(dirname "$0")/../.."

gcloud builds submit \
    --tag "gcr.io/${PROJECT_ID}/${SERVICE_NAME}" \
    --timeout=30m \
    -f deploy/gcp/Dockerfile \
    .

# Deploy to Cloud Run
echo -e "${YELLOW}☁️ Deploying to Cloud Run...${NC}"
gcloud run deploy "${SERVICE_NAME}" \
    --image "gcr.io/${PROJECT_ID}/${SERVICE_NAME}" \
    --region "${REGION}" \
    --platform managed \
    --memory 4Gi \
    --cpu 2 \
    --timeout 900 \
    --concurrency 10 \
    --min-instances 0 \
    --max-instances 100 \
    --set-env-vars "GCS_BUCKET=${GCS_BUCKET}" \
    --set-env-vars "PROXY_PROVIDER=${PROXY_PROVIDER:-brightdata}" \
    --set-env-vars "PROXY_COUNTRY=${PROXY_COUNTRY:-us}" \
    --set-env-vars "VIDEO_QUALITY=${VIDEO_QUALITY:-1080p}" \
    --set-secrets "PROXY_USERNAME=proxy-username:latest,PROXY_PASSWORD=proxy-password:latest" \
    --allow-unauthenticated

# Get the service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format="value(status.url)")
echo -e "${GREEN}✅ Service deployed at: ${SERVICE_URL}${NC}"

# Create Pub/Sub subscription to Cloud Run
echo -e "${YELLOW}🔗 Creating Pub/Sub subscription...${NC}"
gcloud pubsub subscriptions create scrape-urls-push \
    --topic scrape-urls \
    --push-endpoint "${SERVICE_URL}" \
    --ack-deadline 600 \
    --dead-letter-topic scrape-urls-deadletter \
    --max-delivery-attempts 5 \
    2>/dev/null || echo "Subscription already exists, updating..."

# Update subscription if it exists
gcloud pubsub subscriptions update scrape-urls-push \
    --push-endpoint "${SERVICE_URL}" \
    2>/dev/null || true

echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo -e "${YELLOW}📖 Usage:${NC}"
echo "  # Publish URLs to scrape:"
echo "  gcloud pubsub topics publish scrape-urls --message '{\"url\": \"https://youtube.com/watch?v=VIDEO_ID\", \"job_id\": \"job-001\"}'"
echo ""
echo "  # Or use the Python client:"
echo "  from google.cloud import pubsub_v1"
echo "  publisher = pubsub_v1.PublisherClient()"
echo "  topic = f'projects/${PROJECT_ID}/topics/scrape-urls'"
echo "  publisher.publish(topic, json.dumps({'url': 'https://...', 'job_id': 'job-001'}).encode())"
echo ""
echo -e "${YELLOW}📊 Monitor:${NC}"
echo "  gcloud run services logs read ${SERVICE_NAME} --region ${REGION}"
echo ""
echo -e "${YELLOW}🗑️ Cleanup:${NC}"
echo "  gcloud run services delete ${SERVICE_NAME} --region ${REGION}"

