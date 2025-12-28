//! High-performance download manager with chunked and resumable downloads

use crate::client::HttpClient;
use crate::config::ScraperConfig;
use crate::error::{Result, ScraperError};
use bytes::Bytes;
use futures::stream::StreamExt;
use pyo3::prelude::*;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::fs::{self, File, OpenOptions};
use tokio::io::{AsyncSeekExt, AsyncWriteExt};
use tokio::sync::{mpsc, Semaphore};
use tracing::{debug, error, info, warn};
use uuid::Uuid;

/// Progress information for a download
#[pyclass]
#[derive(Debug, Clone)]
pub struct DownloadProgress {
    #[pyo3(get)]
    pub url: String,
    #[pyo3(get)]
    pub downloaded_bytes: u64,
    #[pyo3(get)]
    pub total_bytes: Option<u64>,
    #[pyo3(get)]
    pub percentage: f64,
    #[pyo3(get)]
    pub speed_bytes_per_sec: f64,
    #[pyo3(get)]
    pub eta_secs: Option<f64>,
    #[pyo3(get)]
    pub status: String,
}

#[pymethods]
impl DownloadProgress {
    fn __repr__(&self) -> String {
        format!(
            "DownloadProgress(url={}, downloaded={}, total={:?}, {}%)",
            self.url, self.downloaded_bytes, self.total_bytes, self.percentage as u32
        )
    }
}

/// Result of a completed download
#[pyclass]
#[derive(Debug, Clone)]
pub struct DownloadResult {
    #[pyo3(get)]
    pub url: String,
    #[pyo3(get)]
    pub output_path: String,
    #[pyo3(get)]
    pub size_bytes: u64,
    #[pyo3(get)]
    pub sha256_hash: String,
    #[pyo3(get)]
    pub duration_secs: f64,
    #[pyo3(get)]
    pub avg_speed_bytes_per_sec: f64,
    #[pyo3(get)]
    pub resumed: bool,
    #[pyo3(get)]
    pub chunks_downloaded: u32,
}

#[pymethods]
impl DownloadResult {
    fn __repr__(&self) -> String {
        format!(
            "DownloadResult(url={}, path={}, size={})",
            self.url, self.output_path, self.size_bytes
        )
    }
}

/// Metadata for resumable downloads
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
struct DownloadState {
    url: String,
    output_path: String,
    total_bytes: Option<u64>,
    downloaded_bytes: u64,
    chunk_size: usize,
    partial_hash: String,
    chunks_completed: Vec<(u64, u64)>,
    started_at: chrono::DateTime<chrono::Utc>,
    last_updated: chrono::DateTime<chrono::Utc>,
}

/// High-performance download manager
pub struct DownloadManager {
    client: Arc<HttpClient>,
    config: ScraperConfig,
    semaphore: Arc<Semaphore>,
    active_downloads: Arc<AtomicU64>,
}

impl DownloadManager {
    /// Create a new download manager
    pub fn new(client: Arc<HttpClient>, config: &ScraperConfig) -> Self {
        Self {
            client,
            config: config.clone(),
            semaphore: Arc::new(Semaphore::new(config.max_concurrent_downloads)),
            active_downloads: Arc::new(AtomicU64::new(0)),
        }
    }

    /// Download a single file
    pub async fn download(&self, url: &str, output_path: &Path) -> Result<DownloadResult> {
        let _permit = self.semaphore.acquire().await.map_err(|_| {
            ScraperError::DownloadFailed {
                attempts: 0,
                message: "Semaphore closed".to_string(),
            }
        })?;

        self.active_downloads.fetch_add(1, Ordering::SeqCst);
        let result = self.download_internal(url, output_path).await;
        self.active_downloads.fetch_sub(1, Ordering::SeqCst);

        result
    }

    async fn download_internal(&self, url: &str, output_path: &Path) -> Result<DownloadResult> {
        let start_time = std::time::Instant::now();
        let mut resumed = false;
        let mut chunks_downloaded = 0u32;

        // Create parent directories
        if let Some(parent) = output_path.parent() {
            fs::create_dir_all(parent).await?;
        }

        // Check for existing partial download
        let state_path = self.get_state_path(output_path);
        let mut start_byte = 0u64;

        if self.config.enable_resume {
            if let Ok(state) = self.load_state(&state_path).await {
                if state.url == url {
                    start_byte = state.downloaded_bytes;
                    resumed = true;
                    info!(
                        "Resuming download from byte {}: {}",
                        start_byte, url
                    );
                }
            }
        }

        // Get content length
        let total_bytes = self.client.get_content_length(url).await?;
        let supports_range = self.client.supports_range_requests(url).await?;

        // If we can't resume or don't support range, start fresh
        if resumed && !supports_range {
            warn!("Server doesn't support range requests, starting from beginning");
            start_byte = 0;
            resumed = false;
        }

        // Open file for writing
        let mut file = if resumed && start_byte > 0 {
            let mut f = OpenOptions::new()
                .write(true)
                .open(output_path)
                .await?;
            f.seek(std::io::SeekFrom::Start(start_byte)).await?;
            f
        } else {
            File::create(output_path).await?
        };

        // Download with chunking
        let mut hasher = Sha256::new();
        let mut downloaded = start_byte;

        if supports_range && total_bytes.is_some() && self.config.chunk_size_bytes > 0 {
            // Chunked download for large files
            let total = total_bytes.unwrap();
            let chunk_size = self.config.chunk_size_bytes as u64;

            while downloaded < total {
                let end = (downloaded + chunk_size - 1).min(total - 1);
                
                let response = self.client.get_range(url, downloaded, Some(end)).await?;
                let bytes = response.bytes().await?;
                
                file.write_all(&bytes).await?;
                hasher.update(&bytes);
                
                downloaded += bytes.len() as u64;
                chunks_downloaded += 1;

                // Save state for resume
                if self.config.enable_resume && chunks_downloaded % 10 == 0 {
                    self.save_state(&state_path, &DownloadState {
                        url: url.to_string(),
                        output_path: output_path.to_string_lossy().to_string(),
                        total_bytes,
                        downloaded_bytes: downloaded,
                        chunk_size: self.config.chunk_size_bytes,
                        partial_hash: hex::encode(hasher.clone().finalize()),
                        chunks_completed: vec![(start_byte, downloaded)],
                        started_at: chrono::Utc::now(),
                        last_updated: chrono::Utc::now(),
                    }).await?;
                }

                debug!(
                    "Downloaded chunk {}/{}: {} bytes",
                    chunks_downloaded,
                    (total / chunk_size) + 1,
                    bytes.len()
                );
            }
        } else {
            // Streaming download for smaller files or when range not supported
            let response = if start_byte > 0 {
                self.client.get_range(url, start_byte, None).await?
            } else {
                self.client.get(url).await?
            };

            let mut stream = response.bytes_stream();
            
            while let Some(chunk) = stream.next().await {
                let bytes = chunk?;
                file.write_all(&bytes).await?;
                hasher.update(&bytes);
                downloaded += bytes.len() as u64;
            }
            chunks_downloaded = 1;
        }

        file.flush().await?;
        drop(file);

        // Clean up state file
        if self.config.enable_resume {
            let _ = fs::remove_file(&state_path).await;
        }

        let duration = start_time.elapsed();
        let hash = hex::encode(hasher.finalize());

        Ok(DownloadResult {
            url: url.to_string(),
            output_path: output_path.to_string_lossy().to_string(),
            size_bytes: downloaded,
            sha256_hash: hash,
            duration_secs: duration.as_secs_f64(),
            avg_speed_bytes_per_sec: downloaded as f64 / duration.as_secs_f64(),
            resumed,
            chunks_downloaded,
        })
    }

    /// Download multiple files concurrently
    pub async fn download_batch(
        &self,
        items: Vec<(String, PathBuf)>,
        progress_tx: Option<mpsc::Sender<DownloadProgress>>,
    ) -> Vec<Result<DownloadResult>> {
        let futures: Vec<_> = items
            .into_iter()
            .map(|(url, path)| {
                let manager = self.clone();
                let progress_tx = progress_tx.clone();
                
                async move {
                    let result = manager.download(&url, &path).await;
                    
                    if let Some(tx) = progress_tx {
                        let progress = match &result {
                            Ok(r) => DownloadProgress {
                                url: r.url.clone(),
                                downloaded_bytes: r.size_bytes,
                                total_bytes: Some(r.size_bytes),
                                percentage: 100.0,
                                speed_bytes_per_sec: r.avg_speed_bytes_per_sec,
                                eta_secs: Some(0.0),
                                status: "completed".to_string(),
                            },
                            Err(e) => DownloadProgress {
                                url: url.clone(),
                                downloaded_bytes: 0,
                                total_bytes: None,
                                percentage: 0.0,
                                speed_bytes_per_sec: 0.0,
                                eta_secs: None,
                                status: format!("error: {}", e),
                            },
                        };
                        let _ = tx.send(progress).await;
                    }
                    
                    result
                }
            })
            .collect();

        futures::future::join_all(futures).await
    }

    /// Get the number of active downloads
    pub fn active_downloads(&self) -> u64 {
        self.active_downloads.load(Ordering::SeqCst)
    }

    fn get_state_path(&self, output_path: &Path) -> PathBuf {
        let mut state_path = output_path.to_path_buf();
        let file_name = state_path.file_name().unwrap().to_string_lossy();
        state_path.set_file_name(format!(".{}.dlstate", file_name));
        state_path
    }

    async fn load_state(&self, path: &Path) -> Result<DownloadState> {
        let content = fs::read_to_string(path).await?;
        serde_json::from_str(&content).map_err(|e| e.into())
    }

    async fn save_state(&self, path: &Path, state: &DownloadState) -> Result<()> {
        let content = serde_json::to_string_pretty(state)?;
        fs::write(path, content).await?;
        Ok(())
    }
}

impl Clone for DownloadManager {
    fn clone(&self) -> Self {
        Self {
            client: self.client.clone(),
            config: self.config.clone(),
            semaphore: self.semaphore.clone(),
            active_downloads: self.active_downloads.clone(),
        }
    }
}

/// Python-exposed download manager
#[pyclass]
pub struct PyDownloadManager {
    inner: Arc<DownloadManager>,
    runtime: Arc<tokio::runtime::Runtime>,
}

#[pymethods]
impl PyDownloadManager {
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

        let manager = DownloadManager::new(Arc::new(client), &config);

        Ok(Self {
            inner: Arc::new(manager),
            runtime: Arc::new(runtime),
        })
    }

    /// Download a single file
    pub fn download(&self, url: &str, output_path: &str) -> PyResult<DownloadResult> {
        let manager = self.inner.clone();
        let url = url.to_string();
        let path = PathBuf::from(output_path);

        self.runtime.block_on(async move {
            manager.download(&url, &path).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Download multiple files concurrently
    pub fn download_batch(&self, items: Vec<(String, String)>) -> PyResult<Vec<DownloadResult>> {
        let manager = self.inner.clone();
        let items: Vec<_> = items
            .into_iter()
            .map(|(url, path)| (url, PathBuf::from(path)))
            .collect();

        self.runtime.block_on(async move {
            let results = manager.download_batch(items, None).await;
            
            let mut successes = Vec::new();
            for result in results {
                match result {
                    Ok(r) => successes.push(r),
                    Err(e) => {
                        warn!("Download failed: {}", e);
                    }
                }
            }
            Ok(successes)
        })
    }

    /// Get number of active downloads
    pub fn active_downloads(&self) -> u64 {
        self.inner.active_downloads()
    }
}

