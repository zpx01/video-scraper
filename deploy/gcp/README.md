# GCP Deployment Guide for VideoScraper

## Anti-Ban Strategies

### 1. **Proxy Rotation** (Recommended)
Use residential/datacenter proxy services that handle IP rotation for you.

### 2. **Cloud Run Jobs** (Ephemeral IPs)
Each Cloud Run instance gets a new IP. Scale horizontally.

### 3. **GKE with NAT Gateway Rotation**
Programmatically rotate NAT IPs on a schedule.

### 4. **Multi-Region Distribution**
Spread requests across regions to avoid geographic bans.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Cloud Scheduler                          │
│                    (Triggers every N minutes)                   │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Cloud Pub/Sub                            │
│                      (URL Distribution)                         │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│   │ Topic A  │  │ Topic B  │  │ Topic C  │  │ Topic D  │       │
│   │(youtube) │  │(vimeo)   │  │(twitter) │  │(generic) │       │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
└────────┼─────────────┼─────────────┼─────────────┼──────────────┘
         │             │             │             │
         ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Cloud Run Workers                           │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │Worker 1 │  │Worker 2 │  │Worker 3 │  │Worker N │            │
│  │(us-east)│  │(europe) │  │(asia)   │  │  ...    │            │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘            │
│       │            │            │            │                  │
│       └────────────┴─────┬──────┴────────────┘                  │
│                          │                                      │
│                          ▼                                      │
│              ┌───────────────────────┐                          │
│              │   Proxy Service       │                          │
│              │ (Bright Data/Oxylabs) │                          │
│              └───────────────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Cloud Storage (GCS)                          │
│         Videos + Metadata + Checkpoints + Logs                  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Set up GCP project
gcloud config set project YOUR_PROJECT_ID

# 2. Enable APIs
gcloud services enable \
    run.googleapis.com \
    pubsub.googleapis.com \
    cloudbuild.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com

# 3. Build and deploy
./deploy.sh
```

