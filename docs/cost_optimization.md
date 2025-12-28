# Cost Optimization Analysis: Crawling 1 Million YouTube Videos

## Current Baseline Estimate

Based on our benchmark (0.77 videos/sec with 8 workers):

| Component | Baseline Cost | Notes |
|-----------|---------------|-------|
| **Compute (Cloud Run)** | ~$500 | 15 days × 8 workers × $0.00004/vCPU-sec |
| **Residential Proxies** | ~$7,500 | 1M requests × 7.5KB avg × $15/GB |
| **Storage (metadata only)** | ~$5 | 1GB JSON at $0.02/GB/month |
| **Pub/Sub** | ~$40 | 1M messages × $0.04/100K |
| **Total (metadata only)** | **~$8,000** | |
| **+ Video downloads (1TB)** | **+$15,000** | Proxy bandwidth for actual videos |

**Primary cost driver: Proxy bandwidth (90%+ of costs)**

---

## Optimization Strategies

### 1. 🔄 **Use Datacenter Proxies Instead of Residential**

**Savings: 80-90% on proxy costs**

```
Residential: $15/GB → Datacenter: $1-2/GB
```

| Proxy Type | Cost/GB | Risk | Best For |
|------------|---------|------|----------|
| Residential | $15 | Low | YouTube (anti-bot) |
| Datacenter | $1-2 | Medium | Generic sites |
| ISP Proxies | $5-8 | Low | Compromise |

**Trade-off**: Higher ban risk. Mitigate with:
- Slower rate limits (0.5 req/s)
- User agent rotation
- Request fingerprint randomization

```python
# Switch to datacenter proxies with slower rates
config = ProxyConfig(
    provider="oxylabs",
    proxy_type="datacenter",  # $1/GB vs $15/GB
)
crawler = YouTubeCrawler(
    rate_limit_per_worker=0.3,  # Slower to avoid bans
    num_workers=32,  # More workers to compensate
)
```

**Estimated savings: $6,000-7,000**

---

### 2. 🚫 **Skip Proxy for Metadata-Only Crawls**

**Savings: 90%+ if you only need video IDs/metadata**

YouTube's metadata endpoints are less protected than video downloads:

```python
# Direct requests for metadata (risky but cheap)
crawler = YouTubeCrawler(
    # No proxy for initial discovery
    rate_limit_per_worker=0.1,  # Very slow to avoid bans
    num_workers=50,  # Spread across many IPs via Cloud Run
)
```

**Strategy**: Use 100+ Cloud Run instances (each gets unique IP)
- No proxy costs
- Just Cloud Run compute (~$500)

**Trade-off**: May get IP banned. Use for:
- Initial discovery phase
- Switch to proxies only for video downloads

---

### 3. ⚡ **Use Spot/Preemptible Instances**

**Savings: 60-80% on compute**

```
Regular Cloud Run: $0.00004/vCPU-sec
Spot VMs: $0.00001/vCPU-sec (75% cheaper)
```

```hcl
# Terraform: Use spot instances
resource "google_compute_instance" "crawler" {
  scheduling {
    preemptible = true
    automatic_restart = false
  }
}
```

**Trade-off**: Instances can be terminated. Mitigate with:
- Aggressive checkpointing
- Auto-restart logic
- Distribute across zones

**Estimated savings: $300-400 on compute**

---

### 4. 📦 **Batch API Requests**

**Savings: 50-70% on proxy bandwidth**

Instead of fetching full pages, use YouTube's internal APIs:

```python
# YouTube's batch endpoint (undocumented)
# Single request returns multiple video metadata
async def batch_get_videos(video_ids: List[str]) -> List[dict]:
    # Batch up to 50 videos per request
    endpoint = "https://www.youtube.com/youtubei/v1/player"
    payload = {
        "videoIds": video_ids[:50],
        "context": {...}
    }
    # One request instead of 50
```

**Savings calculation**:
- Current: 1M requests × 50KB = 50GB
- Batched: 20K requests × 100KB = 2GB

**Trade-off**: Uses undocumented API (may break)

---

### 5. 🗄️ **Cache Aggressively**

**Savings: 20-40% on repeated content**

```python
# Redis cache for video metadata
import redis

cache = redis.Redis()

def get_video_info(video_id: str) -> dict:
    # Check cache first
    cached = cache.get(f"yt:{video_id}")
    if cached:
        return json.loads(cached)
    
    # Fetch and cache for 24 hours
    info = fetch_from_youtube(video_id)
    cache.setex(f"yt:{video_id}", 86400, json.dumps(info))
    return info
```

**Best for**:
- Related videos (often repeated)
- Channel info
- Popular videos

---

### 6. 🎯 **Smart Crawl Strategies**

**Savings: Variable (reduce total videos needed)**

#### A. **Bloom Filters for Deduplication**

```python
from pybloom_live import BloomFilter

# Memory-efficient dedup (10MB for 10M items)
seen = BloomFilter(capacity=10_000_000, error_rate=0.001)

def should_crawl(video_id: str) -> bool:
    if video_id in seen:
        return False  # Already seen (probably)
    seen.add(video_id)
    return True
```

#### B. **Priority-Based Crawling**

```python
# Prioritize high-value videos
def priority(video: VideoNode) -> float:
    return (
        video.view_count * 0.5 +
        len(video.related_ids) * 100 +  # More connections = more discovery
        (1.0 / (video.depth + 1)) * 1000  # Prefer shallow
    )
```

#### C. **Topic-Focused Crawling**

Instead of random walk, stay within topics:

```python
# Filter related videos by similarity
def filter_related(current: VideoNode, related: List[VideoNode]) -> List[VideoNode]:
    # Keep only videos with similar titles/channels
    return [r for r in related if similarity(current.title, r.title) > 0.3]
```

---

### 7. 🌍 **Regional Arbitrage**

**Savings: 30-50% on compute**

GCP prices vary by region:

| Region | vCPU/hour | Relative |
|--------|-----------|----------|
| us-central1 | $0.0209 | 100% |
| us-west4 | $0.0209 | 100% |
| asia-south1 (Mumbai) | $0.0156 | 75% |
| southamerica-east1 | $0.0272 | 130% |

```hcl
# Deploy to cheapest region
resource "google_cloud_run_service" "worker" {
  location = "asia-south1"  # 25% cheaper
}
```

---

### 8. 📊 **Tiered Crawling Pipeline**

**Savings: 60-70% overall**

Split into phases with different cost profiles:

```
Phase 1: Discovery (cheap)
├── Cloud Run (no proxy)
├── Metadata only
├── 5M video IDs discovered
└── Cost: ~$200

Phase 2: Filter (free)
├── Local processing
├── Filter to 1M best videos
└── Cost: $0

Phase 3: Download (expensive, targeted)
├── Proxies + storage
├── Only 1M selected videos
└── Cost: ~$2,000 (datacenter proxies)

Total: ~$2,200 vs $8,000 baseline
```

---

### 9. 🔧 **Connection Reuse & HTTP/2**

**Savings: 10-20% on latency → faster completion**

```python
# Reuse connections
session = requests.Session()
adapter = HTTPAdapter(
    pool_connections=100,
    pool_maxsize=100,
    max_retries=3,
)
session.mount("https://", adapter)

# HTTP/2 multiplexing (httpx)
import httpx
client = httpx.AsyncClient(http2=True)
```

---

### 10. ⏰ **Off-Peak Crawling**

**Savings: Minimal direct, but fewer blocks**

YouTube has less aggressive rate limiting during off-peak:
- 2-6 AM local time (per region)
- Weekdays vs weekends

```python
# Schedule crawls for off-peak
from datetime import datetime

def should_crawl_now() -> bool:
    hour = datetime.now().hour
    return 2 <= hour <= 6  # Off-peak window
```

---

## Optimized Cost Estimate

| Strategy | Baseline | Optimized | Savings |
|----------|----------|-----------|---------|
| Compute | $500 | $150 (spot + Mumbai) | 70% |
| Proxies | $7,500 | $750 (datacenter + batching) | 90% |
| Storage | $5 | $5 | 0% |
| Pub/Sub | $40 | $10 | 75% |
| **Total** | **$8,045** | **$915** | **89%** |

### Implementation Priority

1. **High Impact, Easy**: Datacenter proxies, spot instances
2. **High Impact, Medium**: Tiered pipeline, batching
3. **Medium Impact, Easy**: Regional arbitrage, caching
4. **Low Impact**: Connection reuse, off-peak timing

---

## Quick Wins Checklist

- [ ] Switch from residential to datacenter/ISP proxies
- [ ] Use spot/preemptible instances
- [ ] Deploy to asia-south1 (cheapest region)
- [ ] Implement tiered discovery → download pipeline
- [ ] Add Redis caching for repeated video IDs
- [ ] Use Bloom filter for memory-efficient dedup
- [ ] Batch API requests where possible
- [ ] Checkpoint every 100 videos for spot instance recovery

