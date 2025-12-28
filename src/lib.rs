//! VideoScraper - High-performance video content scraping infrastructure
//!
//! A Rust-powered library with Python bindings for large-scale video scraping.
//!
//! # Features
//!
//! - **High Performance**: Built in Rust with async I/O for maximum throughput
//! - **Resumable Downloads**: Automatic resume for interrupted downloads
//! - **Rate Limiting**: Built-in rate limiting to respect server limits
//! - **Multiple Backends**: Support for local, S3, and GCS storage
//! - **Video Extraction**: Automatic extraction of video URLs from web pages
//! - **Pipeline Processing**: Orchestrate complex scraping workflows
//!
//! # Python Usage
//!
//! ```python
//! from videoscraper import Pipeline, ScraperConfig, VideoFilter
//!
//! # Create a pipeline with custom config
//! config = ScraperConfig.high_performance()
//! pipeline = Pipeline(config)
//!
//! # Add URLs to scrape
//! pipeline.add_urls([
//!     "https://example.com/video1",
//!     "https://example.com/video2",
//! ])
//!
//! # Run with concurrency
//! pipeline.run(concurrency=32)
//!
//! # Check results
//! for job in pipeline.jobs():
//!     print(f"{job.id}: {job.status}")
//! ```

pub mod client;
pub mod config;
pub mod downloader;
pub mod error;
pub mod extractor;
pub mod pipeline;
pub mod storage;

use pyo3::prelude::*;

// Re-exports for Rust usage
pub use client::HttpClient;
pub use config::{ScraperConfig, StorageConfig};
pub use downloader::{DownloadManager, DownloadProgress, DownloadResult};
pub use error::{Result, ScraperError};
pub use extractor::{VideoExtractor, VideoFormat, VideoInfo, ExtractionResult};
pub use pipeline::{ScrapingPipeline, ScrapeJob, JobStatus, PipelineStats, VideoFilter};
pub use storage::{StorageBackend, StorageManager, ObjectMetadata};

/// Python module definition
#[pymodule]
fn _core(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("videoscraper=info".parse().unwrap()),
        )
        .try_init()
        .ok();

    // Configuration classes
    m.add_class::<config::ScraperConfig>()?;
    m.add_class::<config::StorageConfig>()?;

    // HTTP client
    m.add_class::<client::PyHttpClient>()?;

    // Downloader
    m.add_class::<downloader::PyDownloadManager>()?;
    m.add_class::<downloader::DownloadProgress>()?;
    m.add_class::<downloader::DownloadResult>()?;

    // Extractor
    m.add_class::<extractor::PyVideoExtractor>()?;
    m.add_class::<extractor::VideoInfo>()?;
    m.add_class::<extractor::VideoFormat>()?;
    m.add_class::<extractor::ExtractionResult>()?;

    // Storage
    m.add_class::<storage::PyStorage>()?;
    m.add_class::<storage::ObjectMetadata>()?;

    // Pipeline
    m.add_class::<pipeline::PyPipeline>()?;
    m.add_class::<pipeline::ScrapeJob>()?;
    m.add_class::<pipeline::JobStatus>()?;
    m.add_class::<pipeline::PipelineStats>()?;
    m.add_class::<pipeline::VideoFilter>()?;

    // Version info
    m.add("__version__", "0.1.0")?;

    // Convenience function to create a default pipeline
    #[pyfn(m)]
    fn create_pipeline(
        config: Option<&config::ScraperConfig>,
        storage_config: Option<&config::StorageConfig>,
    ) -> PyResult<pipeline::PyPipeline> {
        pipeline::PyPipeline::new(config, storage_config)
    }

    // Convenience function to extract videos from a URL
    #[pyfn(m)]
    fn extract_videos(url: &str) -> PyResult<Vec<extractor::VideoInfo>> {
        let config = config::ScraperConfig::default();
        let extractor = extractor::PyVideoExtractor::new(Some(&config))?;
        extractor.extract_from_url(url)
    }

    // Convenience function to download a file
    #[pyfn(m)]
    fn download_file(url: &str, output_path: &str) -> PyResult<downloader::DownloadResult> {
        let config = config::ScraperConfig::default();
        let manager = downloader::PyDownloadManager::new(Some(&config))?;
        manager.download(url, output_path)
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_default() {
        let config = ScraperConfig::default();
        assert_eq!(config.max_concurrent_downloads, 32);
        assert!(config.enable_resume);
    }

    #[test]
    fn test_config_high_performance() {
        let config = ScraperConfig::high_performance();
        assert_eq!(config.max_concurrent_downloads, 128);
        assert_eq!(config.rate_limit_per_second, 50.0);
    }

    #[test]
    fn test_storage_config_local() {
        let config = StorageConfig::local("/tmp/videos");
        assert_eq!(config.backend, "local");
        assert_eq!(config.local_path, "/tmp/videos");
    }

    #[test]
    fn test_storage_config_s3() {
        let config = StorageConfig::s3("my-bucket", Some("us-west-2"), None, None);
        assert_eq!(config.backend, "s3");
        assert_eq!(config.s3_bucket, Some("my-bucket".to_string()));
        assert_eq!(config.s3_region, Some("us-west-2".to_string()));
    }
}

