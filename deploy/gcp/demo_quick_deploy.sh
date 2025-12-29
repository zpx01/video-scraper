#!/bin/bash
#
# VideoScraper Quick GCP Demo Deployment
# ======================================
#
# This script provides a minimal GCP deployment for testing purposes.
# It deploys without proxy support (limited throughput due to rate limits).
#
# Usage:
#   export GCP_PROJECT_ID="your-project-id"
#   ./demo_quick_deploy.sh
#
# For production deployment with proxies, use deploy.sh instead.
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="videoscraper-demo"
BUCKET_NAME="videoscraper-demo-${PROJECT_ID}"

echo -e "${BOLD}${BLUE}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║         VideoScraper GCP Quick Demo Deployment           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check prerequisites
echo -e "${CYAN}Checking prerequisites...${NC}"

if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}❌ gcloud CLI not found${NC}"
    echo "   Install from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} gcloud CLI"

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}❌ GCP_PROJECT_ID not set${NC}"
    echo "   Run: export GCP_PROJECT_ID='your-project-id'"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Project ID: $PROJECT_ID"

# Confirm deployment
echo ""
echo -e "${YELLOW}This will deploy to:${NC}"
echo "  Project: $PROJECT_ID"
echo "  Region: $REGION"
echo "  Service: $SERVICE_NAME"
echo "  Bucket: $BUCKET_NAME"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# Set project
echo -e "\n${CYAN}Step 1/6: Setting GCP project...${NC}"
gcloud config set project "$PROJECT_ID"

# Enable APIs
echo -e "\n${CYAN}Step 2/6: Enabling APIs...${NC}"
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    pubsub.googleapis.com \
    storage.googleapis.com \
    --quiet

echo -e "  ${GREEN}✓${NC} APIs enabled"

# Create bucket
echo -e "\n${CYAN}Step 3/6: Creating storage bucket...${NC}"
if gsutil ls -b "gs://$BUCKET_NAME" &> /dev/null; then
    echo -e "  ${YELLOW}⚠${NC} Bucket already exists"
else
    gsutil mb -l "$REGION" "gs://$BUCKET_NAME"
    echo -e "  ${GREEN}✓${NC} Bucket created: gs://$BUCKET_NAME"
fi

# Build Docker image
echo -e "\n${CYAN}Step 4/6: Building Docker image...${NC}"
echo "  This may take 5-10 minutes..."

# Navigate to project root
cd "$(dirname "$0")/../.."

# Create a cloudbuild.yaml for the build
cat > /tmp/cloudbuild.yaml << EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/${PROJECT_ID}/${SERVICE_NAME}', '-f', 'deploy/gcp/Dockerfile', '.']
images:
  - 'gcr.io/${PROJECT_ID}/${SERVICE_NAME}'
timeout: '1800s'
EOF

gcloud builds submit \
    --config=/tmp/cloudbuild.yaml \
    --timeout=30m \
    --quiet

echo -e "  ${GREEN}✓${NC} Image built: gcr.io/$PROJECT_ID/$SERVICE_NAME"

# Deploy to Cloud Run
echo -e "\n${CYAN}Step 5/6: Deploying to Cloud Run...${NC}"
gcloud run deploy "$SERVICE_NAME" \
    --image "gcr.io/$PROJECT_ID/$SERVICE_NAME" \
    --region "$REGION" \
    --platform managed \
    --memory 4Gi \
    --cpu 2 \
    --timeout 900 \
    --concurrency 5 \
    --min-instances 0 \
    --max-instances 10 \
    --set-env-vars "GCS_BUCKET=$BUCKET_NAME,VIDEO_QUALITY=720p" \
    --allow-unauthenticated \
    --quiet

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region "$REGION" \
    --format="value(status.url)")

echo -e "  ${GREEN}✓${NC} Deployed: $SERVICE_URL"

# Set up Pub/Sub
echo -e "\n${CYAN}Step 6/6: Setting up Pub/Sub...${NC}"

gcloud pubsub topics create scrape-urls-demo 2>/dev/null || true
gcloud pubsub subscriptions create scrape-urls-demo-push \
    --topic scrape-urls-demo \
    --push-endpoint "$SERVICE_URL" \
    --ack-deadline 600 \
    2>/dev/null || \
    gcloud pubsub subscriptions update scrape-urls-demo-push \
        --push-endpoint "$SERVICE_URL"

echo -e "  ${GREEN}✓${NC} Pub/Sub configured"

# Summary
echo -e "\n${BOLD}${GREEN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║              ✓ Deployment Complete!                      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${BOLD}Service URL:${NC} $SERVICE_URL"
echo -e "${BOLD}GCS Bucket:${NC} gs://$BUCKET_NAME"
echo ""

echo -e "${CYAN}Quick Test Commands:${NC}"
echo ""
echo "  # Health check"
echo "  curl $SERVICE_URL/health"
echo ""
echo "  # Test direct scrape (YouTube)"
echo "  curl -X POST $SERVICE_URL/scrape \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"url\": \"https://www.youtube.com/watch?v=dQw4w9WgXcQ\", \"job_id\": \"test-001\"}'"
echo ""
echo "  # Test via Pub/Sub"
echo "  gcloud pubsub topics publish scrape-urls-demo \\"
echo "    --message '{\"url\": \"https://www.youtube.com/watch?v=dQw4w9WgXcQ\", \"job_id\": \"pubsub-001\"}'"
echo ""
echo "  # View logs"
echo "  gcloud run services logs tail $SERVICE_NAME --region $REGION"
echo ""
echo "  # Check downloaded videos"
echo "  gsutil ls gs://$BUCKET_NAME/videos/"
echo ""

echo -e "${YELLOW}⚠ Note: Without proxy support, you may hit rate limits.${NC}"
echo -e "   For production use, configure proxy credentials and use deploy.sh"
echo ""

echo -e "${CYAN}Cleanup when done:${NC}"
echo "  gcloud run services delete $SERVICE_NAME --region $REGION"
echo "  gcloud pubsub subscriptions delete scrape-urls-demo-push"
echo "  gcloud pubsub topics delete scrape-urls-demo"
echo "  gsutil rm -r gs://$BUCKET_NAME"

