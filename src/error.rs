//! Error types for the video scraper system

use pyo3::exceptions::PyRuntimeError;
use pyo3::PyErr;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum ScraperError {
    #[error("HTTP request failed: {0}")]
    HttpError(#[from] reqwest::Error),

    #[error("URL parsing failed: {0}")]
    UrlError(#[from] url::ParseError),

    #[error("JSON parsing failed: {0}")]
    JsonError(#[from] serde_json::Error),

    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),

    #[error("Rate limit exceeded, retry after {retry_after_secs} seconds")]
    RateLimited { retry_after_secs: u64 },

    #[error("Download failed after {attempts} attempts: {message}")]
    DownloadFailed { attempts: u32, message: String },

    #[error("Extraction failed: {0}")]
    ExtractionFailed(String),

    #[error("Storage error: {0}")]
    StorageError(String),

    #[error("Configuration error: {0}")]
    ConfigError(String),

    #[error("Pipeline error: {0}")]
    PipelineError(String),

    #[error("Timeout after {timeout_secs} seconds")]
    Timeout { timeout_secs: u64 },

    #[error("Invalid video format: {0}")]
    InvalidFormat(String),

    #[error("Video not found: {0}")]
    NotFound(String),

    #[error("Access denied: {0}")]
    AccessDenied(String),

    #[error("Chunk verification failed: expected {expected}, got {actual}")]
    ChunkVerificationFailed { expected: String, actual: String },

    #[error("AWS S3 error: {0}")]
    S3Error(String),

    #[error("GCS error: {0}")]
    GcsError(String),
}

impl From<ScraperError> for PyErr {
    fn from(err: ScraperError) -> PyErr {
        PyRuntimeError::new_err(err.to_string())
    }
}

pub type Result<T> = std::result::Result<T, ScraperError>;

