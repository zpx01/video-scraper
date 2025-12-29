# Local Residential Proxy

Expose your home IP as a proxy for YouTube scraping from GCP.

## Why?

YouTube blocks datacenter IPs (like GCP Cloud Run). By routing requests through your residential IP, you can bypass these blocks.

## Quick Start

### 1. Start the Proxy Server

```bash
# From project root
make local-proxy

# Or directly
python deploy/proxy/simple_proxy_server.py
```

Output:
```
🏠 Local Residential Proxy Server
==================================
📝 Credentials:
   Username: videoscraper
   Password: testpass123

✅ Proxy running!
   Local:  http://videoscraper:testpass123@localhost:8888
```

### 2. Expose via ngrok

```bash
# Install ngrok (if needed)
brew install ngrok

# Get auth token from https://dashboard.ngrok.com
ngrok config add-authtoken YOUR_TOKEN

# Expose the proxy
ngrok tcp 8888
```

Output:
```
Forwarding  tcp://0.tcp.ngrok.io:12345 -> localhost:8888
```

### 3. Update Cloud Run

```bash
gcloud run services update videoscraper-demo \
    --set-env-vars "PROXY_PROVIDER=custom,PROXY_HOST=0.tcp.ngrok.io,PROXY_PORT=12345,PROXY_USERNAME=videoscraper,PROXY_PASSWORD=testpass123" \
    --region us-central1
```

### 4. Test

```bash
curl -X POST https://YOUR-SERVICE.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=aqz-KE-bpKQ"}'
```

## Files

| File | Description |
|------|-------------|
| `simple_proxy_server.py` | Lightweight Python proxy (no dependencies) |
| `local_proxy_setup.sh` | Full setup with Squid + ngrok automation |

## How It Works

```
┌─────────────────┐     ┌─────────────┐     ┌───────────────┐
│  GCP Cloud Run  │────▶│   ngrok     │────▶│  Your Laptop  │
│  (videoscraper) │     │  (tunnel)   │     │  (proxy)      │
└─────────────────┘     └─────────────┘     └───────┬───────┘
                                                     │
                                                     ▼
                                            ┌───────────────┐
                                            │   YouTube     │
                                            │ (sees home IP)│
                                            └───────────────┘
```

## Configuration

### Custom Port

```bash
PROXY_PORT=9999 python deploy/proxy/simple_proxy_server.py
```

### Custom Credentials

```bash
PROXY_USER=myuser PROXY_PASSWORD=mypass python deploy/proxy/simple_proxy_server.py
```

## Production Alternatives

For production, use a commercial residential proxy provider:

| Provider | Website | Pricing |
|----------|---------|---------|
| Bright Data | brightdata.com | ~$15/GB |
| Oxylabs | oxylabs.io | ~$15/GB |
| SmartProxy | smartproxy.com | ~$12/GB |

## Troubleshooting

### "Connection refused"

Make sure the proxy server is running:
```bash
curl -x http://videoscraper:testpass123@localhost:8888 https://httpbin.org/ip
```

### ngrok not connecting

Verify your auth token:
```bash
ngrok config check
```

### Still getting blocked

Some YouTube endpoints may require cookies. Consider:
1. Exporting cookies from your browser
2. Using a different video URL
3. Adding delays between requests

