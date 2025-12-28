//! Configuration types for the video scraper system

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Global scraper configuration
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScraperConfig {
    /// Maximum concurrent downloads
    #[pyo3(get, set)]
    pub max_concurrent_downloads: usize,

    /// Maximum concurrent requests per domain
    #[pyo3(get, set)]
    pub max_requests_per_domain: usize,

    /// Request timeout in seconds
    #[pyo3(get, set)]
    pub request_timeout_secs: u64,

    /// Download chunk size in bytes (default: 8MB)
    #[pyo3(get, set)]
    pub chunk_size_bytes: usize,

    /// Enable resume for interrupted downloads
    #[pyo3(get, set)]
    pub enable_resume: bool,

    /// Maximum retry attempts
    #[pyo3(get, set)]
    pub max_retries: u32,

    /// Base delay between retries in milliseconds
    #[pyo3(get, set)]
    pub retry_delay_ms: u64,

    /// User agent string
    #[pyo3(get, set)]
    pub user_agent: String,

    /// Respect robots.txt
    #[pyo3(get, set)]
    pub respect_robots_txt: bool,

    /// Rate limit: requests per second per domain
    #[pyo3(get, set)]
    pub rate_limit_per_second: f64,

    /// Enable request caching
    #[pyo3(get, set)]
    pub enable_caching: bool,

    /// Cache directory path
    #[pyo3(get, set)]
    pub cache_dir: String,

    /// Verify downloaded content checksums
    #[pyo3(get, set)]
    pub verify_checksums: bool,

    /// Maximum file size to download (0 = unlimited)
    #[pyo3(get, set)]
    pub max_file_size_bytes: u64,

    /// Minimum file size to download (filter small files)
    #[pyo3(get, set)]
    pub min_file_size_bytes: u64,

    /// Allowed video formats
    #[pyo3(get, set)]
    pub allowed_formats: Vec<String>,

    /// Proxy URL (optional)
    #[pyo3(get, set)]
    pub proxy_url: Option<String>,

    /// Number of worker threads (0 = auto)
    #[pyo3(get, set)]
    pub worker_threads: usize,

    /// Enable compression for requests
    #[pyo3(get, set)]
    pub enable_compression: bool,

    /// Connection pool size per host
    #[pyo3(get, set)]
    pub pool_size_per_host: usize,

    /// Idle connection timeout in seconds
    #[pyo3(get, set)]
    pub idle_timeout_secs: u64,
}

impl Default for ScraperConfig {
    fn default() -> Self {
        Self {
            max_concurrent_downloads: 32,
            max_requests_per_domain: 8,
            request_timeout_secs: 300,
            chunk_size_bytes: 8 * 1024 * 1024, // 8MB chunks
            enable_resume: true,
            max_retries: 5,
            retry_delay_ms: 1000,
            user_agent: format!(
                "VideoScraper/0.1.0 (Rust/Python; +https://github.com/videoscraper)"
            ),
            respect_robots_txt: true,
            rate_limit_per_second: 2.0,
            enable_caching: true,
            cache_dir: ".cache/videoscraper".to_string(),
            verify_checksums: true,
            max_file_size_bytes: 0, // Unlimited
            min_file_size_bytes: 0,
            allowed_formats: vec![
                "mp4".to_string(),
                "webm".to_string(),
                "mkv".to_string(),
                "m3u8".to_string(),
                "ts".to_string(),
            ],
            proxy_url: None,
            worker_threads: 0, // Auto-detect
            enable_compression: true,
            pool_size_per_host: 16,
            idle_timeout_secs: 90,
        }
    }
}

#[pymethods]
impl ScraperConfig {
    #[new]
    #[pyo3(signature = ())]
    pub fn new() -> Self {
        Self::default()
    }

    /// Create a high-performance configuration for large-scale scraping
    #[staticmethod]
    pub fn high_performance() -> Self {
        Self {
            max_concurrent_downloads: 128,
            max_requests_per_domain: 16,
            request_timeout_secs: 600,
            chunk_size_bytes: 16 * 1024 * 1024, // 16MB chunks
            enable_resume: true,
            max_retries: 10,
            retry_delay_ms: 500,
            user_agent: format!(
                "VideoScraper/0.1.0 (Rust/Python; +https://github.com/videoscraper)"
            ),
            respect_robots_txt: false,
            rate_limit_per_second: 50.0,
            enable_caching: true,
            cache_dir: ".cache/videoscraper".to_string(),
            verify_checksums: true,
            max_file_size_bytes: 0,
            min_file_size_bytes: 0,
            allowed_formats: vec![
                "mp4".to_string(),
                "webm".to_string(),
                "mkv".to_string(),
                "m3u8".to_string(),
                "ts".to_string(),
            ],
            proxy_url: None,
            worker_threads: 0,
            enable_compression: true,
            pool_size_per_host: 32,
            idle_timeout_secs: 120,
        }
    }

    /// Create a conservative configuration that respects rate limits
    #[staticmethod]
    pub fn conservative() -> Self {
        Self {
            max_concurrent_downloads: 4,
            max_requests_per_domain: 2,
            request_timeout_secs: 120,
            chunk_size_bytes: 4 * 1024 * 1024, // 4MB chunks
            enable_resume: true,
            max_retries: 3,
            retry_delay_ms: 2000,
            user_agent: format!(
                "VideoScraper/0.1.0 (Rust/Python; +https://github.com/videoscraper)"
            ),
            respect_robots_txt: true,
            rate_limit_per_second: 0.5,
            enable_caching: true,
            cache_dir: ".cache/videoscraper".to_string(),
            verify_checksums: true,
            max_file_size_bytes: 0,
            min_file_size_bytes: 0,
            allowed_formats: vec![
                "mp4".to_string(),
                "webm".to_string(),
                "mkv".to_string(),
            ],
            proxy_url: None,
            worker_threads: 0,
            enable_compression: true,
            pool_size_per_host: 8,
            idle_timeout_secs: 60,
        }
    }

    /// Convert to JSON string
    pub fn to_json(&self) -> PyResult<String> {
        serde_json::to_string_pretty(self).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Serialization failed: {}", e))
        })
    }

    /// Load from JSON string
    #[staticmethod]
    pub fn from_json(json_str: &str) -> PyResult<Self> {
        serde_json::from_str(json_str).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Deserialization failed: {}", e))
        })
    }
}

/// Storage backend configuration
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageConfig {
    /// Storage backend type: "local", "s3", "gcs"
    #[pyo3(get, set)]
    pub backend: String,

    /// Local storage path (for local backend)
    #[pyo3(get, set)]
    pub local_path: String,

    /// S3 bucket name
    #[pyo3(get, set)]
    pub s3_bucket: Option<String>,

    /// S3 region
    #[pyo3(get, set)]
    pub s3_region: Option<String>,

    /// S3 endpoint (for S3-compatible storage)
    #[pyo3(get, set)]
    pub s3_endpoint: Option<String>,

    /// GCS bucket name
    #[pyo3(get, set)]
    pub gcs_bucket: Option<String>,

    /// GCS project ID
    #[pyo3(get, set)]
    pub gcs_project: Option<String>,

    /// Key prefix for cloud storage
    #[pyo3(get, set)]
    pub key_prefix: String,

    /// Enable multipart uploads for large files
    #[pyo3(get, set)]
    pub enable_multipart: bool,

    /// Multipart upload threshold in bytes
    #[pyo3(get, set)]
    pub multipart_threshold_bytes: u64,

    /// Part size for multipart uploads
    #[pyo3(get, set)]
    pub multipart_part_size_bytes: u64,
}

impl Default for StorageConfig {
    fn default() -> Self {
        Self {
            backend: "local".to_string(),
            local_path: "./downloads".to_string(),
            s3_bucket: None,
            s3_region: Some("us-east-1".to_string()),
            s3_endpoint: None,
            gcs_bucket: None,
            gcs_project: None,
            key_prefix: "videos/".to_string(),
            enable_multipart: true,
            multipart_threshold_bytes: 100 * 1024 * 1024, // 100MB
            multipart_part_size_bytes: 64 * 1024 * 1024,  // 64MB parts
        }
    }
}

#[pymethods]
impl StorageConfig {
    #[new]
    #[pyo3(signature = ())]
    pub fn new() -> Self {
        Self::default()
    }

    /// Create local storage configuration
    #[staticmethod]
    pub fn local(path: &str) -> Self {
        Self {
            backend: "local".to_string(),
            local_path: path.to_string(),
            ..Default::default()
        }
    }

    /// Create S3 storage configuration
    #[staticmethod]
    #[pyo3(signature = (bucket, region=None, endpoint=None, key_prefix=None))]
    pub fn s3(
        bucket: &str,
        region: Option<&str>,
        endpoint: Option<&str>,
        key_prefix: Option<&str>,
    ) -> Self {
        Self {
            backend: "s3".to_string(),
            s3_bucket: Some(bucket.to_string()),
            s3_region: region.map(|s| s.to_string()),
            s3_endpoint: endpoint.map(|s| s.to_string()),
            key_prefix: key_prefix.unwrap_or("videos/").to_string(),
            ..Default::default()
        }
    }

    /// Create GCS storage configuration
    #[staticmethod]
    #[pyo3(signature = (bucket, project=None, key_prefix=None))]
    pub fn gcs(bucket: &str, project: Option<&str>, key_prefix: Option<&str>) -> Self {
        Self {
            backend: "gcs".to_string(),
            gcs_bucket: Some(bucket.to_string()),
            gcs_project: project.map(|s| s.to_string()),
            key_prefix: key_prefix.unwrap_or("videos/").to_string(),
            ..Default::default()
        }
    }
}

