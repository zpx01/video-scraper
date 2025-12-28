//! High-performance HTTP client with connection pooling and rate limiting

use crate::config::ScraperConfig;
use crate::error::{Result, ScraperError};
use dashmap::DashMap;
use governor::{Quota, RateLimiter};
use pyo3::prelude::*;
use reqwest::{
    header::{HeaderMap, HeaderValue, ACCEPT, ACCEPT_ENCODING, RANGE, USER_AGENT},
    Client, Response, StatusCode,
};
use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::sleep;
use tracing::{debug, info, warn};
use url::Url;

type DomainRateLimiter = RateLimiter<
    governor::state::NotKeyed,
    governor::state::InMemoryState,
    governor::clock::DefaultClock,
>;

/// HTTP client with automatic rate limiting and connection pooling
pub struct HttpClient {
    client: Client,
    config: ScraperConfig,
    rate_limiters: Arc<DashMap<String, Arc<DomainRateLimiter>>>,
}

impl HttpClient {
    /// Create a new HTTP client with the given configuration
    pub fn new(config: &ScraperConfig) -> Result<Self> {
        let mut headers = HeaderMap::new();
        headers.insert(USER_AGENT, HeaderValue::from_str(&config.user_agent).unwrap());
        headers.insert(
            ACCEPT,
            HeaderValue::from_static("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        );
        if config.enable_compression {
            headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("gzip, deflate, br"));
        }

        let mut builder = Client::builder()
            .default_headers(headers)
            .timeout(Duration::from_secs(config.request_timeout_secs))
            .connect_timeout(Duration::from_secs(30))
            .pool_max_idle_per_host(config.pool_size_per_host)
            .pool_idle_timeout(Duration::from_secs(config.idle_timeout_secs))
            .tcp_keepalive(Duration::from_secs(60))
            .tcp_nodelay(true)
            .gzip(config.enable_compression)
            .brotli(config.enable_compression)
            .deflate(config.enable_compression);

        if let Some(ref proxy_url) = config.proxy_url {
            let proxy = reqwest::Proxy::all(proxy_url).map_err(|e| {
                ScraperError::ConfigError(format!("Invalid proxy URL: {}", e))
            })?;
            builder = builder.proxy(proxy);
        }

        let client = builder.build()?;

        Ok(Self {
            client,
            config: config.clone(),
            rate_limiters: Arc::new(DashMap::new()),
        })
    }

    /// Get or create a rate limiter for a domain
    fn get_rate_limiter(&self, domain: &str) -> Arc<DomainRateLimiter> {
        if let Some(limiter) = self.rate_limiters.get(domain) {
            return limiter.clone();
        }

        let rate = self.config.rate_limit_per_second;
        let quota = if rate >= 1.0 {
            Quota::per_second(NonZeroU32::new(rate as u32).unwrap_or(NonZeroU32::new(1).unwrap()))
        } else {
            // For rates < 1 per second, use per-minute quota
            let per_min = (rate * 60.0).max(1.0) as u32;
            Quota::per_minute(NonZeroU32::new(per_min).unwrap())
        };

        let limiter = Arc::new(RateLimiter::direct(quota));
        self.rate_limiters.insert(domain.to_string(), limiter.clone());
        limiter
    }

    /// Extract domain from URL for rate limiting
    fn get_domain(url: &str) -> Result<String> {
        let parsed = Url::parse(url)?;
        Ok(parsed.host_str().unwrap_or("unknown").to_string())
    }

    /// Wait for rate limit if needed
    async fn wait_for_rate_limit(&self, url: &str) -> Result<()> {
        let domain = Self::get_domain(url)?;
        let limiter = self.get_rate_limiter(&domain);
        
        // Wait until we can make a request
        limiter.until_ready().await;
        Ok(())
    }

    /// Perform a GET request with automatic retries
    pub async fn get(&self, url: &str) -> Result<Response> {
        self.get_with_headers(url, None).await
    }

    /// Perform a GET request with custom headers
    pub async fn get_with_headers(
        &self,
        url: &str,
        headers: Option<HeaderMap>,
    ) -> Result<Response> {
        self.wait_for_rate_limit(url).await?;

        let mut attempt = 0;
        let max_retries = self.config.max_retries;
        let base_delay = Duration::from_millis(self.config.retry_delay_ms);

        loop {
            attempt += 1;
            debug!("HTTP GET attempt {}/{}: {}", attempt, max_retries, url);

            let mut request = self.client.get(url);
            if let Some(ref h) = headers {
                request = request.headers(h.clone());
            }

            match request.send().await {
                Ok(response) => {
                    let status = response.status();
                    
                    if status.is_success() || status == StatusCode::PARTIAL_CONTENT {
                        return Ok(response);
                    }

                    if status == StatusCode::TOO_MANY_REQUESTS {
                        // Check for Retry-After header
                        let retry_after = response
                            .headers()
                            .get("Retry-After")
                            .and_then(|v| v.to_str().ok())
                            .and_then(|s| s.parse::<u64>().ok())
                            .unwrap_or(60);

                        warn!(
                            "Rate limited on {}, waiting {} seconds",
                            url, retry_after
                        );

                        if attempt >= max_retries {
                            return Err(ScraperError::RateLimited {
                                retry_after_secs: retry_after,
                            });
                        }

                        sleep(Duration::from_secs(retry_after)).await;
                        continue;
                    }

                    if status == StatusCode::NOT_FOUND {
                        return Err(ScraperError::NotFound(url.to_string()));
                    }

                    if status == StatusCode::FORBIDDEN || status == StatusCode::UNAUTHORIZED {
                        return Err(ScraperError::AccessDenied(url.to_string()));
                    }

                    // Retry on server errors
                    if status.is_server_error() && attempt < max_retries {
                        let delay = base_delay * 2u32.pow(attempt - 1);
                        warn!(
                            "Server error {} on {}, retrying in {:?}",
                            status, url, delay
                        );
                        sleep(delay).await;
                        continue;
                    }

                    return Err(ScraperError::HttpError(
                        response.error_for_status().unwrap_err(),
                    ));
                }
                Err(e) => {
                    if attempt >= max_retries {
                        return Err(ScraperError::DownloadFailed {
                            attempts: attempt,
                            message: e.to_string(),
                        });
                    }

                    let delay = base_delay * 2u32.pow(attempt - 1);
                    warn!("Request failed: {}, retrying in {:?}", e, delay);
                    sleep(delay).await;
                }
            }
        }
    }

    /// Perform a range request for partial content
    pub async fn get_range(&self, url: &str, start: u64, end: Option<u64>) -> Result<Response> {
        self.wait_for_rate_limit(url).await?;

        let range_header = match end {
            Some(e) => format!("bytes={}-{}", start, e),
            None => format!("bytes={}-", start),
        };

        let mut headers = HeaderMap::new();
        headers.insert(RANGE, HeaderValue::from_str(&range_header).unwrap());

        self.get_with_headers(url, Some(headers)).await
    }

    /// Get content length without downloading
    pub async fn get_content_length(&self, url: &str) -> Result<Option<u64>> {
        self.wait_for_rate_limit(url).await?;

        let response = self.client.head(url).send().await?;

        if !response.status().is_success() {
            return Ok(None);
        }

        let length = response
            .headers()
            .get("content-length")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse::<u64>().ok());

        Ok(length)
    }

    /// Check if server supports range requests
    pub async fn supports_range_requests(&self, url: &str) -> Result<bool> {
        self.wait_for_rate_limit(url).await?;

        let response = self.client.head(url).send().await?;

        let accept_ranges = response
            .headers()
            .get("accept-ranges")
            .and_then(|v| v.to_str().ok())
            .map(|s| s != "none")
            .unwrap_or(false);

        Ok(accept_ranges)
    }

    /// Get the underlying reqwest client
    pub fn inner(&self) -> &Client {
        &self.client
    }
}

/// Python-exposed HTTP client wrapper
#[pyclass]
pub struct PyHttpClient {
    inner: Arc<HttpClient>,
    runtime: Arc<tokio::runtime::Runtime>,
}

#[pymethods]
impl PyHttpClient {
    #[new]
    #[pyo3(signature = (config=None))]
    pub fn new(config: Option<&ScraperConfig>) -> PyResult<Self> {
        let config = config.cloned().unwrap_or_default();
        let runtime = tokio::runtime::Runtime::new().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create runtime: {}", e))
        })?;

        let client = HttpClient::new(&config).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create client: {}", e))
        })?;

        Ok(Self {
            inner: Arc::new(client),
            runtime: Arc::new(runtime),
        })
    }

    /// Fetch URL and return response body as string
    pub fn get_text(&self, url: &str) -> PyResult<String> {
        let client = self.inner.clone();
        let url = url.to_string();

        self.runtime.block_on(async move {
            let response = client.get(&url).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })?;

            response.text().await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Fetch URL and return response body as bytes
    pub fn get_bytes(&self, url: &str) -> PyResult<Vec<u8>> {
        let client = self.inner.clone();
        let url = url.to_string();

        self.runtime.block_on(async move {
            let response = client.get(&url).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })?;

            response.bytes().await.map(|b| b.to_vec()).map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Get content length for a URL
    pub fn get_content_length(&self, url: &str) -> PyResult<Option<u64>> {
        let client = self.inner.clone();
        let url = url.to_string();

        self.runtime.block_on(async move {
            client.get_content_length(&url).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Check if URL supports range requests
    pub fn supports_range_requests(&self, url: &str) -> PyResult<bool> {
        let client = self.inner.clone();
        let url = url.to_string();

        self.runtime.block_on(async move {
            client.supports_range_requests(&url).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }
}

