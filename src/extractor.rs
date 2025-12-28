//! Video URL extraction from web pages

use crate::client::HttpClient;
use crate::error::{Result, ScraperError};
use pyo3::prelude::*;
use regex::Regex;
use scraper::{Html, Selector};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::Arc;
use tracing::{debug, info, warn};
use url::Url;

/// Extracted video information
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VideoInfo {
    #[pyo3(get)]
    pub url: String,
    #[pyo3(get)]
    pub title: Option<String>,
    #[pyo3(get)]
    pub description: Option<String>,
    #[pyo3(get)]
    pub duration_secs: Option<u64>,
    #[pyo3(get)]
    pub width: Option<u32>,
    #[pyo3(get)]
    pub height: Option<u32>,
    #[pyo3(get)]
    pub format: Option<String>,
    #[pyo3(get)]
    pub file_size_bytes: Option<u64>,
    #[pyo3(get)]
    pub thumbnail_url: Option<String>,
    #[pyo3(get)]
    pub source_page: String,
    #[pyo3(get)]
    pub quality: Option<String>,
    #[pyo3(get)]
    pub codec: Option<String>,
}

#[pymethods]
impl VideoInfo {
    fn __repr__(&self) -> String {
        format!(
            "VideoInfo(url={}, title={:?}, format={:?})",
            self.url, self.title, self.format
        )
    }

    /// Convert to JSON string
    pub fn to_json(&self) -> PyResult<String> {
        serde_json::to_string_pretty(self).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Serialization failed: {}", e))
        })
    }
}

/// Video format/quality option
#[pyclass]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VideoFormat {
    #[pyo3(get)]
    pub format_id: String,
    #[pyo3(get)]
    pub url: String,
    #[pyo3(get)]
    pub ext: String,
    #[pyo3(get)]
    pub quality: Option<String>,
    #[pyo3(get)]
    pub width: Option<u32>,
    #[pyo3(get)]
    pub height: Option<u32>,
    #[pyo3(get)]
    pub fps: Option<u32>,
    #[pyo3(get)]
    pub vcodec: Option<String>,
    #[pyo3(get)]
    pub acodec: Option<String>,
    #[pyo3(get)]
    pub filesize: Option<u64>,
    #[pyo3(get)]
    pub tbr: Option<f64>, // Total bitrate
}

#[pymethods]
impl VideoFormat {
    fn __repr__(&self) -> String {
        format!(
            "VideoFormat(id={}, ext={}, quality={:?}, {}x{})",
            self.format_id,
            self.ext,
            self.quality,
            self.width.unwrap_or(0),
            self.height.unwrap_or(0)
        )
    }
}

/// Result of extraction with multiple formats
#[pyclass]
#[derive(Debug, Clone)]
pub struct ExtractionResult {
    #[pyo3(get)]
    pub source_url: String,
    #[pyo3(get)]
    pub title: Option<String>,
    #[pyo3(get)]
    pub description: Option<String>,
    #[pyo3(get)]
    pub thumbnail: Option<String>,
    #[pyo3(get)]
    pub duration: Option<u64>,
    #[pyo3(get)]
    pub formats: Vec<VideoFormat>,
    #[pyo3(get)]
    pub best_video_url: Option<String>,
    #[pyo3(get)]
    pub best_audio_url: Option<String>,
}

#[pymethods]
impl ExtractionResult {
    fn __repr__(&self) -> String {
        format!(
            "ExtractionResult(url={}, title={:?}, formats={})",
            self.source_url,
            self.title,
            self.formats.len()
        )
    }

    /// Get the best quality video format
    pub fn get_best_format(&self) -> Option<VideoFormat> {
        self.formats
            .iter()
            .filter(|f| f.vcodec.is_some() && f.vcodec.as_ref().map(|v| v != "none").unwrap_or(true))
            .max_by_key(|f| f.height.unwrap_or(0))
            .cloned()
    }

    /// Get format by quality (e.g., "1080p", "720p")
    pub fn get_format_by_quality(&self, quality: &str) -> Option<VideoFormat> {
        let height: u32 = quality.trim_end_matches('p').parse().unwrap_or(0);
        self.formats
            .iter()
            .find(|f| f.height == Some(height))
            .cloned()
    }
}

/// Generic video URL extractor
pub struct VideoExtractor {
    client: Arc<HttpClient>,
    video_extensions: Vec<String>,
    video_patterns: Vec<Regex>,
}

impl VideoExtractor {
    pub fn new(client: Arc<HttpClient>) -> Self {
        let video_patterns = vec![
            // Direct video file URLs
            Regex::new(r#"https?://[^\s"'<>]+\.(mp4|webm|mkv|avi|mov|m4v)(\?[^\s"'<>]*)?"#).unwrap(),
            // HLS/DASH streams
            Regex::new(r#"https?://[^\s"'<>]+\.(m3u8|mpd)(\?[^\s"'<>]*)?"#).unwrap(),
            // Video source patterns
            Regex::new(r#"(?:src|source|file|url|video_url|videoUrl|video-url)["']?\s*[:=]\s*["']?(https?://[^\s"'<>]+\.(mp4|webm|m3u8))"#).unwrap(),
            // JSON patterns
            Regex::new(r#""(https?://[^"]+\.(mp4|webm|m3u8)[^"]*)""#).unwrap(),
        ];

        Self {
            client,
            video_extensions: vec![
                "mp4".to_string(),
                "webm".to_string(),
                "mkv".to_string(),
                "avi".to_string(),
                "mov".to_string(),
                "m4v".to_string(),
                "m3u8".to_string(),
                "mpd".to_string(),
                "ts".to_string(),
            ],
            video_patterns,
        }
    }

    /// Extract video URLs from a page
    pub async fn extract_from_url(&self, url: &str) -> Result<Vec<VideoInfo>> {
        let response = self.client.get(url).await?;
        let html = response.text().await?;
        self.extract_from_html(&html, url)
    }

    /// Extract video URLs from HTML content
    pub fn extract_from_html(&self, html: &str, source_url: &str) -> Result<Vec<VideoInfo>> {
        let mut videos = Vec::new();
        let mut seen_urls = HashSet::new();

        // Parse HTML
        let document = Html::parse_document(html);

        // Extract page title
        let title_selector = Selector::parse("title").unwrap();
        let page_title = document
            .select(&title_selector)
            .next()
            .map(|el| el.text().collect::<String>());

        // Extract from <video> elements
        let video_selector = Selector::parse("video").unwrap();
        for video_el in document.select(&video_selector) {
            // Check src attribute
            if let Some(src) = video_el.value().attr("src") {
                if let Some(video) = self.create_video_info(src, source_url, &page_title, &mut seen_urls) {
                    videos.push(video);
                }
            }

            // Check poster for thumbnail
            let thumbnail = video_el.value().attr("poster").map(|s| {
                self.resolve_url(s, source_url).unwrap_or_else(|_| s.to_string())
            });

            // Check <source> children
            let source_selector = Selector::parse("source").unwrap();
            for source_el in video_el.select(&source_selector) {
                if let Some(src) = source_el.value().attr("src") {
                    if let Some(mut video) = self.create_video_info(src, source_url, &page_title, &mut seen_urls) {
                        video.thumbnail_url = thumbnail.clone();
                        
                        // Extract type/format
                        if let Some(type_attr) = source_el.value().attr("type") {
                            video.format = Some(type_attr.to_string());
                        }
                        
                        videos.push(video);
                    }
                }
            }
        }

        // Extract from <iframe> elements (embedded players)
        let iframe_selector = Selector::parse("iframe").unwrap();
        for iframe in document.select(&iframe_selector) {
            if let Some(src) = iframe.value().attr("src") {
                // Check for video platform embeds
                if src.contains("youtube.com/embed")
                    || src.contains("player.vimeo.com")
                    || src.contains("dailymotion.com/embed")
                {
                    debug!("Found embedded video player: {}", src);
                    // These require special handling - note for Python layer
                }
            }
        }

        // Extract from <a> links to video files
        let link_selector = Selector::parse("a[href]").unwrap();
        for link in document.select(&link_selector) {
            if let Some(href) = link.value().attr("href") {
                if self.is_video_url(href) {
                    if let Some(video) = self.create_video_info(href, source_url, &page_title, &mut seen_urls) {
                        videos.push(video);
                    }
                }
            }
        }

        // Extract from meta tags (og:video, etc.)
        let meta_selector = Selector::parse("meta").unwrap();
        for meta in document.select(&meta_selector) {
            let property = meta.value().attr("property").or_else(|| meta.value().attr("name"));
            let content = meta.value().attr("content");

            if let (Some(prop), Some(content)) = (property, content) {
                if prop == "og:video" || prop == "og:video:url" || prop == "og:video:secure_url" {
                    if let Some(video) = self.create_video_info(content, source_url, &page_title, &mut seen_urls) {
                        videos.push(video);
                    }
                }
            }
        }

        // Extract using regex patterns from raw HTML/scripts
        for pattern in &self.video_patterns {
            for cap in pattern.captures_iter(html) {
                if let Some(url_match) = cap.get(1).or_else(|| cap.get(0)) {
                    let url = url_match.as_str();
                    if self.is_video_url(url) {
                        if let Some(video) = self.create_video_info(url, source_url, &page_title, &mut seen_urls) {
                            videos.push(video);
                        }
                    }
                }
            }
        }

        info!("Extracted {} video URLs from {}", videos.len(), source_url);
        Ok(videos)
    }

    fn create_video_info(
        &self,
        url: &str,
        source_url: &str,
        page_title: &Option<String>,
        seen_urls: &mut HashSet<String>,
    ) -> Option<VideoInfo> {
        // Resolve relative URLs
        let resolved = match self.resolve_url(url, source_url) {
            Ok(u) => u,
            Err(_) => return None,
        };

        // Skip if already seen
        if seen_urls.contains(&resolved) {
            return None;
        }
        seen_urls.insert(resolved.clone());

        // Extract format from URL
        let format = self.extract_format(&resolved);

        Some(VideoInfo {
            url: resolved,
            title: page_title.clone(),
            description: None,
            duration_secs: None,
            width: None,
            height: None,
            format,
            file_size_bytes: None,
            thumbnail_url: None,
            source_page: source_url.to_string(),
            quality: None,
            codec: None,
        })
    }

    fn resolve_url(&self, url: &str, base: &str) -> Result<String> {
        if url.starts_with("http://") || url.starts_with("https://") {
            return Ok(url.to_string());
        }

        if url.starts_with("//") {
            return Ok(format!("https:{}", url));
        }

        let base_url = Url::parse(base)?;
        let resolved = base_url.join(url)?;
        Ok(resolved.to_string())
    }

    fn is_video_url(&self, url: &str) -> bool {
        let lower = url.to_lowercase();
        self.video_extensions
            .iter()
            .any(|ext| {
                lower.contains(&format!(".{}", ext))
                    || lower.contains(&format!(".{}?", ext))
                    || lower.contains(&format!(".{}&", ext))
            })
    }

    fn extract_format(&self, url: &str) -> Option<String> {
        let lower = url.to_lowercase();
        for ext in &self.video_extensions {
            if lower.contains(&format!(".{}", ext)) {
                return Some(ext.clone());
            }
        }
        None
    }

    /// Extract quality from URL or filename
    pub fn extract_quality(&self, url: &str) -> Option<String> {
        let patterns = [
            (r"2160[pP]|4[kK]", "2160p"),
            (r"1440[pP]|2[kK]", "1440p"),
            (r"1080[pP]|[fF][hH][dD]", "1080p"),
            (r"720[pP]|[hH][dD]", "720p"),
            (r"480[pP]|[sS][dD]", "480p"),
            (r"360[pP]", "360p"),
            (r"240[pP]", "240p"),
            (r"144[pP]", "144p"),
        ];

        for (pattern, quality) in patterns {
            if let Ok(re) = Regex::new(pattern) {
                if re.is_match(url) {
                    return Some(quality.to_string());
                }
            }
        }
        None
    }
}

/// Python-exposed video extractor
#[pyclass]
pub struct PyVideoExtractor {
    inner: Arc<VideoExtractor>,
    runtime: Arc<tokio::runtime::Runtime>,
}

#[pymethods]
impl PyVideoExtractor {
    #[new]
    #[pyo3(signature = (config=None))]
    pub fn new(config: Option<&crate::config::ScraperConfig>) -> PyResult<Self> {
        let config = config.cloned().unwrap_or_default();
        let runtime = tokio::runtime::Runtime::new().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create runtime: {}", e))
        })?;

        let client = HttpClient::new(&config).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create client: {}", e))
        })?;

        let extractor = VideoExtractor::new(Arc::new(client));

        Ok(Self {
            inner: Arc::new(extractor),
            runtime: Arc::new(runtime),
        })
    }

    /// Extract video URLs from a web page
    pub fn extract_from_url(&self, url: &str) -> PyResult<Vec<VideoInfo>> {
        let extractor = self.inner.clone();
        let url = url.to_string();

        self.runtime.block_on(async move {
            extractor.extract_from_url(&url).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Extract video URLs from HTML content
    pub fn extract_from_html(&self, html: &str, source_url: &str) -> PyResult<Vec<VideoInfo>> {
        self.inner.extract_from_html(html, source_url).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
        })
    }

    /// Extract quality information from a URL
    pub fn extract_quality(&self, url: &str) -> Option<String> {
        self.inner.extract_quality(url)
    }
}

/// Site-specific extractor trait for platforms like YouTube
pub trait SiteExtractor: Send + Sync {
    fn name(&self) -> &str;
    fn can_handle(&self, url: &str) -> bool;
    fn extract(&self, url: &str) -> Result<ExtractionResult>;
}

/// YouTube extractor placeholder (full implementation would need yt-dlp integration)
pub struct YouTubeExtractor {
    client: Arc<HttpClient>,
}

impl YouTubeExtractor {
    pub fn new(client: Arc<HttpClient>) -> Self {
        Self { client }
    }
}

impl SiteExtractor for YouTubeExtractor {
    fn name(&self) -> &str {
        "youtube"
    }

    fn can_handle(&self, url: &str) -> bool {
        url.contains("youtube.com") || url.contains("youtu.be")
    }

    fn extract(&self, url: &str) -> Result<ExtractionResult> {
        // Note: Full YouTube extraction requires yt-dlp or similar
        // This is a placeholder showing the interface
        warn!(
            "YouTube extraction requires yt-dlp integration. URL: {}",
            url
        );

        Ok(ExtractionResult {
            source_url: url.to_string(),
            title: None,
            description: None,
            thumbnail: None,
            duration: None,
            formats: vec![],
            best_video_url: None,
            best_audio_url: None,
        })
    }
}

