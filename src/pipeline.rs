//! Pipeline orchestration for video scraping workflows

use crate::client::HttpClient;
use crate::config::{ScraperConfig, StorageConfig};
use crate::downloader::{DownloadManager, DownloadProgress, DownloadResult};
use crate::error::{Result, ScraperError};
use crate::extractor::{VideoExtractor, VideoInfo};
use crate::storage::{LocalStorage, StorageBackend};
use async_channel::{bounded, Receiver, Sender};
use futures::stream::{self, StreamExt};
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

/// Job status in the pipeline
#[pyclass]
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum JobStatus {
    Pending,
    Extracting,
    Downloading,
    Uploading,
    Completed,
    Failed,
    Cancelled,
}

#[pymethods]
impl JobStatus {
    fn __repr__(&self) -> String {
        format!("{:?}", self)
    }
}

/// A single scraping job
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScrapeJob {
    #[pyo3(get)]
    pub id: String,
    #[pyo3(get)]
    pub source_url: String,
    #[pyo3(get)]
    pub status: JobStatus,
    #[pyo3(get)]
    pub video_url: Option<String>,
    #[pyo3(get)]
    pub output_path: Option<String>,
    #[pyo3(get)]
    pub storage_key: Option<String>,
    #[pyo3(get)]
    pub error_message: Option<String>,
    #[pyo3(get)]
    pub bytes_downloaded: u64,
    #[pyo3(get)]
    pub total_bytes: Option<u64>,
    #[pyo3(get)]
    pub created_at: String,
    #[pyo3(get)]
    pub completed_at: Option<String>,
}

impl ScrapeJob {
    pub fn new(source_url: &str) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            source_url: source_url.to_string(),
            status: JobStatus::Pending,
            video_url: None,
            output_path: None,
            storage_key: None,
            error_message: None,
            bytes_downloaded: 0,
            total_bytes: None,
            created_at: chrono::Utc::now().to_rfc3339(),
            completed_at: None,
        }
    }
}

#[pymethods]
impl ScrapeJob {
    fn __repr__(&self) -> String {
        format!(
            "ScrapeJob(id={}, url={}, status={:?})",
            self.id, self.source_url, self.status
        )
    }

    /// Check if job is terminal (completed or failed)
    pub fn is_terminal(&self) -> bool {
        matches!(self.status, JobStatus::Completed | JobStatus::Failed | JobStatus::Cancelled)
    }

    /// Get progress percentage
    pub fn progress_percent(&self) -> f64 {
        match self.total_bytes {
            Some(total) if total > 0 => (self.bytes_downloaded as f64 / total as f64) * 100.0,
            _ => 0.0,
        }
    }
}

/// Pipeline statistics
#[pyclass]
#[derive(Debug, Clone, Default)]
pub struct PipelineStats {
    #[pyo3(get)]
    pub total_jobs: u64,
    #[pyo3(get)]
    pub pending_jobs: u64,
    #[pyo3(get)]
    pub active_jobs: u64,
    #[pyo3(get)]
    pub completed_jobs: u64,
    #[pyo3(get)]
    pub failed_jobs: u64,
    #[pyo3(get)]
    pub total_bytes_downloaded: u64,
    #[pyo3(get)]
    pub videos_extracted: u64,
    #[pyo3(get)]
    pub avg_download_speed: f64,
}

#[pymethods]
impl PipelineStats {
    fn __repr__(&self) -> String {
        format!(
            "PipelineStats(total={}, active={}, completed={}, failed={})",
            self.total_jobs, self.active_jobs, self.completed_jobs, self.failed_jobs
        )
    }
}

/// Filter criteria for video selection
#[pyclass]
#[derive(Debug, Clone, Default)]
pub struct VideoFilter {
    #[pyo3(get, set)]
    pub min_width: Option<u32>,
    #[pyo3(get, set)]
    pub min_height: Option<u32>,
    #[pyo3(get, set)]
    pub max_width: Option<u32>,
    #[pyo3(get, set)]
    pub max_height: Option<u32>,
    #[pyo3(get, set)]
    pub allowed_formats: Vec<String>,
    #[pyo3(get, set)]
    pub min_duration_secs: Option<u64>,
    #[pyo3(get, set)]
    pub max_duration_secs: Option<u64>,
    #[pyo3(get, set)]
    pub min_size_bytes: Option<u64>,
    #[pyo3(get, set)]
    pub max_size_bytes: Option<u64>,
    #[pyo3(get, set)]
    pub quality_preference: Vec<String>, // e.g., ["1080p", "720p", "480p"]
}

#[pymethods]
impl VideoFilter {
    #[new]
    #[pyo3(signature = ())]
    pub fn new() -> Self {
        Self::default()
    }

    /// Create a filter for HD content (720p+)
    #[staticmethod]
    pub fn hd() -> Self {
        Self {
            min_height: Some(720),
            allowed_formats: vec!["mp4".to_string(), "webm".to_string()],
            quality_preference: vec!["1080p".to_string(), "720p".to_string()],
            ..Default::default()
        }
    }

    /// Create a filter for 4K content
    #[staticmethod]
    pub fn uhd() -> Self {
        Self {
            min_height: Some(2160),
            allowed_formats: vec!["mp4".to_string(), "webm".to_string(), "mkv".to_string()],
            quality_preference: vec!["2160p".to_string(), "1440p".to_string()],
            ..Default::default()
        }
    }

    /// Check if a video matches this filter
    pub fn matches(&self, video: &VideoInfo) -> bool {
        // Check dimensions
        if let Some(min_w) = self.min_width {
            if video.width.map(|w| w < min_w).unwrap_or(false) {
                return false;
            }
        }
        if let Some(max_w) = self.max_width {
            if video.width.map(|w| w > max_w).unwrap_or(false) {
                return false;
            }
        }
        if let Some(min_h) = self.min_height {
            if video.height.map(|h| h < min_h).unwrap_or(false) {
                return false;
            }
        }
        if let Some(max_h) = self.max_height {
            if video.height.map(|h| h > max_h).unwrap_or(false) {
                return false;
            }
        }

        // Check format
        if !self.allowed_formats.is_empty() {
            if let Some(ref format) = video.format {
                if !self.allowed_formats.iter().any(|f| format.contains(f)) {
                    return false;
                }
            }
        }

        // Check duration
        if let Some(min_dur) = self.min_duration_secs {
            if video.duration_secs.map(|d| d < min_dur).unwrap_or(false) {
                return false;
            }
        }
        if let Some(max_dur) = self.max_duration_secs {
            if video.duration_secs.map(|d| d > max_dur).unwrap_or(false) {
                return false;
            }
        }

        // Check file size
        if let Some(min_size) = self.min_size_bytes {
            if video.file_size_bytes.map(|s| s < min_size).unwrap_or(false) {
                return false;
            }
        }
        if let Some(max_size) = self.max_size_bytes {
            if video.file_size_bytes.map(|s| s > max_size).unwrap_or(false) {
                return false;
            }
        }

        true
    }
}

/// Main scraping pipeline
pub struct ScrapingPipeline {
    config: ScraperConfig,
    storage_config: StorageConfig,
    client: Arc<HttpClient>,
    downloader: Arc<DownloadManager>,
    extractor: Arc<VideoExtractor>,
    jobs: Arc<RwLock<Vec<ScrapeJob>>>,
    seen_urls: Arc<RwLock<HashSet<String>>>,
    stats: Arc<RwLock<PipelineStats>>,
    job_sender: Sender<ScrapeJob>,
    job_receiver: Receiver<ScrapeJob>,
    running: Arc<std::sync::atomic::AtomicBool>,
}

impl ScrapingPipeline {
    /// Create a new scraping pipeline
    pub fn new(config: &ScraperConfig, storage_config: &StorageConfig) -> Result<Self> {
        let client = Arc::new(HttpClient::new(config)?);
        let downloader = Arc::new(DownloadManager::new(client.clone(), config));
        let extractor = Arc::new(VideoExtractor::new(client.clone()));
        let (sender, receiver) = bounded(10000);

        Ok(Self {
            config: config.clone(),
            storage_config: storage_config.clone(),
            client,
            downloader,
            extractor,
            jobs: Arc::new(RwLock::new(Vec::new())),
            seen_urls: Arc::new(RwLock::new(HashSet::new())),
            stats: Arc::new(RwLock::new(PipelineStats::default())),
            job_sender: sender,
            job_receiver: receiver,
            running: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        })
    }

    /// Add a URL to the scraping queue
    pub async fn add_url(&self, url: &str) -> Result<ScrapeJob> {
        // Check for duplicates
        {
            let seen = self.seen_urls.read().await;
            if seen.contains(url) {
                return Err(ScraperError::PipelineError(format!(
                    "URL already in queue: {}",
                    url
                )));
            }
        }

        let job = ScrapeJob::new(url);
        
        {
            let mut seen = self.seen_urls.write().await;
            seen.insert(url.to_string());
        }
        
        {
            let mut jobs = self.jobs.write().await;
            jobs.push(job.clone());
        }
        
        {
            let mut stats = self.stats.write().await;
            stats.total_jobs += 1;
            stats.pending_jobs += 1;
        }

        self.job_sender.send(job.clone()).await.map_err(|e| {
            ScraperError::PipelineError(format!("Failed to queue job: {}", e))
        })?;

        Ok(job)
    }

    /// Add multiple URLs to the queue
    pub async fn add_urls(&self, urls: Vec<String>) -> Vec<Result<ScrapeJob>> {
        let mut results = Vec::with_capacity(urls.len());
        for url in urls {
            results.push(self.add_url(&url).await);
        }
        results
    }

    /// Process a single job
    async fn process_job(&self, mut job: ScrapeJob, filter: Option<&VideoFilter>) -> ScrapeJob {
        info!("Processing job {}: {}", job.id, job.source_url);

        // Update stats
        {
            let mut stats = self.stats.write().await;
            stats.pending_jobs = stats.pending_jobs.saturating_sub(1);
            stats.active_jobs += 1;
        }

        // Step 1: Extract video URLs
        job.status = JobStatus::Extracting;
        let videos = match self.extractor.extract_from_url(&job.source_url).await {
            Ok(v) => v,
            Err(e) => {
                error!("Extraction failed for {}: {}", job.source_url, e);
                job.status = JobStatus::Failed;
                job.error_message = Some(format!("Extraction failed: {}", e));
                job.completed_at = Some(chrono::Utc::now().to_rfc3339());
                
                let mut stats = self.stats.write().await;
                stats.active_jobs = stats.active_jobs.saturating_sub(1);
                stats.failed_jobs += 1;
                
                return job;
            }
        };

        if videos.is_empty() {
            warn!("No videos found at {}", job.source_url);
            job.status = JobStatus::Failed;
            job.error_message = Some("No videos found".to_string());
            job.completed_at = Some(chrono::Utc::now().to_rfc3339());
            
            let mut stats = self.stats.write().await;
            stats.active_jobs = stats.active_jobs.saturating_sub(1);
            stats.failed_jobs += 1;
            
            return job;
        }

        {
            let mut stats = self.stats.write().await;
            stats.videos_extracted += videos.len() as u64;
        }

        // Step 2: Filter and select best video
        let selected_video = if let Some(filter) = filter {
            videos.into_iter().find(|v| filter.matches(v))
        } else {
            videos.into_iter().next()
        };

        let video = match selected_video {
            Some(v) => v,
            None => {
                job.status = JobStatus::Failed;
                job.error_message = Some("No videos matched filter criteria".to_string());
                job.completed_at = Some(chrono::Utc::now().to_rfc3339());
                
                let mut stats = self.stats.write().await;
                stats.active_jobs = stats.active_jobs.saturating_sub(1);
                stats.failed_jobs += 1;
                
                return job;
            }
        };

        job.video_url = Some(video.url.clone());

        // Step 3: Download video
        job.status = JobStatus::Downloading;
        
        // Generate output path
        let file_ext = video.format.as_deref().unwrap_or("mp4");
        let file_name = format!("{}.{}", job.id, file_ext);
        let output_path = PathBuf::from(&self.storage_config.local_path).join(&file_name);
        job.output_path = Some(output_path.to_string_lossy().to_string());

        // Get content length
        if let Ok(Some(size)) = self.client.get_content_length(&video.url).await {
            job.total_bytes = Some(size);
        }

        match self.downloader.download(&video.url, &output_path).await {
            Ok(result) => {
                job.bytes_downloaded = result.size_bytes;
                job.storage_key = Some(format!("{}{}", self.storage_config.key_prefix, file_name));
                
                let mut stats = self.stats.write().await;
                stats.total_bytes_downloaded += result.size_bytes;
            }
            Err(e) => {
                error!("Download failed for {}: {}", video.url, e);
                job.status = JobStatus::Failed;
                job.error_message = Some(format!("Download failed: {}", e));
                job.completed_at = Some(chrono::Utc::now().to_rfc3339());
                
                let mut stats = self.stats.write().await;
                stats.active_jobs = stats.active_jobs.saturating_sub(1);
                stats.failed_jobs += 1;
                
                return job;
            }
        }

        // Step 4: Mark as completed (storage upload happens separately if needed)
        job.status = JobStatus::Completed;
        job.completed_at = Some(chrono::Utc::now().to_rfc3339());
        
        {
            let mut stats = self.stats.write().await;
            stats.active_jobs = stats.active_jobs.saturating_sub(1);
            stats.completed_jobs += 1;
        }

        info!("Job {} completed successfully", job.id);
        job
    }

    /// Run the pipeline with given concurrency
    pub async fn run(&self, concurrency: usize, filter: Option<VideoFilter>) {
        self.running.store(true, Ordering::SeqCst);
        let filter = Arc::new(filter);

        let results: Vec<_> = stream::unfold(self.job_receiver.clone(), |receiver| async move {
            match receiver.recv().await {
                Ok(job) => Some((job, receiver)),
                Err(_) => None,
            }
        })
        .map(|job| {
            let pipeline = self;
            let filter = filter.clone();
            async move {
                pipeline.process_job(job, filter.as_ref().as_ref()).await
            }
        })
        .buffer_unordered(concurrency)
        .collect()
        .await;

        // Update job states
        let mut jobs = self.jobs.write().await;
        for result in results {
            if let Some(job) = jobs.iter_mut().find(|j| j.id == result.id) {
                *job = result;
            }
        }

        self.running.store(false, Ordering::SeqCst);
    }

    /// Get current statistics
    pub async fn stats(&self) -> PipelineStats {
        self.stats.read().await.clone()
    }

    /// Get all jobs
    pub async fn jobs(&self) -> Vec<ScrapeJob> {
        self.jobs.read().await.clone()
    }

    /// Get a specific job by ID
    pub async fn get_job(&self, id: &str) -> Option<ScrapeJob> {
        self.jobs.read().await.iter().find(|j| j.id == id).cloned()
    }

    /// Check if pipeline is running
    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    /// Stop the pipeline
    pub fn stop(&self) {
        self.running.store(false, Ordering::SeqCst);
        self.job_sender.close();
    }
}

/// Python-exposed pipeline
#[pyclass]
pub struct PyPipeline {
    inner: Arc<tokio::sync::Mutex<ScrapingPipeline>>,
    runtime: Arc<tokio::runtime::Runtime>,
}

#[pymethods]
impl PyPipeline {
    #[new]
    #[pyo3(signature = (config=None, storage_config=None))]
    pub fn new(
        config: Option<&ScraperConfig>,
        storage_config: Option<&StorageConfig>,
    ) -> PyResult<Self> {
        let config = config.cloned().unwrap_or_default();
        let storage_config = storage_config.cloned().unwrap_or_default();

        let runtime = tokio::runtime::Runtime::new().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create runtime: {}", e))
        })?;

        let pipeline = ScrapingPipeline::new(&config, &storage_config).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create pipeline: {}", e))
        })?;

        Ok(Self {
            inner: Arc::new(tokio::sync::Mutex::new(pipeline)),
            runtime: Arc::new(runtime),
        })
    }

    /// Add a URL to the pipeline
    pub fn add_url(&self, url: &str) -> PyResult<ScrapeJob> {
        let inner = self.inner.clone();
        let url = url.to_string();

        self.runtime.block_on(async move {
            let pipeline = inner.lock().await;
            pipeline.add_url(&url).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Add multiple URLs to the pipeline
    pub fn add_urls(&self, urls: Vec<String>) -> PyResult<Vec<ScrapeJob>> {
        let inner = self.inner.clone();

        self.runtime.block_on(async move {
            let pipeline = inner.lock().await;
            let results = pipeline.add_urls(urls).await;
            
            let mut jobs = Vec::new();
            for result in results {
                match result {
                    Ok(job) => jobs.push(job),
                    Err(e) => warn!("Failed to add URL: {}", e),
                }
            }
            Ok(jobs)
        })
    }

    /// Run the pipeline (blocking)
    #[pyo3(signature = (concurrency=None, filter=None))]
    pub fn run(&self, concurrency: Option<usize>, filter: Option<&VideoFilter>) -> PyResult<()> {
        let inner = self.inner.clone();
        let concurrency = concurrency.unwrap_or(16);
        let filter = filter.cloned();

        self.runtime.block_on(async move {
            let pipeline = inner.lock().await;
            pipeline.run(concurrency, filter).await;
            Ok(())
        })
    }

    /// Get pipeline statistics
    pub fn stats(&self) -> PyResult<PipelineStats> {
        let inner = self.inner.clone();

        self.runtime.block_on(async move {
            let pipeline = inner.lock().await;
            Ok(pipeline.stats().await)
        })
    }

    /// Get all jobs
    pub fn jobs(&self) -> PyResult<Vec<ScrapeJob>> {
        let inner = self.inner.clone();

        self.runtime.block_on(async move {
            let pipeline = inner.lock().await;
            Ok(pipeline.jobs().await)
        })
    }

    /// Get a specific job
    pub fn get_job(&self, id: &str) -> PyResult<Option<ScrapeJob>> {
        let inner = self.inner.clone();
        let id = id.to_string();

        self.runtime.block_on(async move {
            let pipeline = inner.lock().await;
            Ok(pipeline.get_job(&id).await)
        })
    }

    /// Check if pipeline is running
    pub fn is_running(&self) -> PyResult<bool> {
        let inner = self.inner.clone();

        self.runtime.block_on(async move {
            let pipeline = inner.lock().await;
            Ok(pipeline.is_running())
        })
    }

    /// Stop the pipeline
    pub fn stop(&self) -> PyResult<()> {
        let inner = self.inner.clone();

        self.runtime.block_on(async move {
            let pipeline = inner.lock().await;
            pipeline.stop();
            Ok(())
        })
    }
}

