//! Storage backends for downloaded video content

use crate::config::StorageConfig;
use crate::error::{Result, ScraperError};
use async_trait::async_trait;
use bytes::Bytes;
use pyo3::prelude::*;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::fs::{self, File};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tracing::info;

/// Metadata for stored objects
#[pyclass]
#[derive(Debug, Clone)]
pub struct ObjectMetadata {
    #[pyo3(get)]
    pub key: String,
    #[pyo3(get)]
    pub size_bytes: u64,
    #[pyo3(get)]
    pub content_type: Option<String>,
    #[pyo3(get)]
    pub etag: Option<String>,
    #[pyo3(get)]
    pub last_modified: Option<String>,
}

#[pymethods]
impl ObjectMetadata {
    fn __repr__(&self) -> String {
        format!("ObjectMetadata(key={}, size={})", self.key, self.size_bytes)
    }
}

/// Storage backend trait
#[async_trait]
pub trait StorageBackend: Send + Sync {
    /// Store bytes at the given key
    async fn put(&self, key: &str, data: Bytes) -> Result<ObjectMetadata>;

    /// Store a local file at the given key
    async fn put_file(&self, key: &str, local_path: &Path) -> Result<ObjectMetadata>;

    /// Get bytes for the given key
    async fn get(&self, key: &str) -> Result<Bytes>;

    /// Download to a local file
    async fn get_file(&self, key: &str, local_path: &Path) -> Result<()>;

    /// Check if a key exists
    async fn exists(&self, key: &str) -> Result<bool>;

    /// Delete an object
    async fn delete(&self, key: &str) -> Result<()>;

    /// List objects with a prefix
    async fn list(&self, prefix: &str) -> Result<Vec<ObjectMetadata>>;

    /// Get metadata for an object
    async fn metadata(&self, key: &str) -> Result<ObjectMetadata>;

    /// Get the backend type name
    fn backend_type(&self) -> &str;
}

/// Local filesystem storage backend
pub struct LocalStorage {
    base_path: PathBuf,
}

impl LocalStorage {
    pub fn new(base_path: &str) -> Result<Self> {
        let path = PathBuf::from(base_path);
        Ok(Self { base_path: path })
    }

    fn get_full_path(&self, key: &str) -> PathBuf {
        self.base_path.join(key)
    }
}

#[async_trait]
impl StorageBackend for LocalStorage {
    async fn put(&self, key: &str, data: Bytes) -> Result<ObjectMetadata> {
        let path = self.get_full_path(key);

        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).await?;
        }

        let mut file = File::create(&path).await?;
        file.write_all(&data).await?;
        file.flush().await?;

        let size = data.len() as u64;
        info!("Stored {} bytes to local path: {:?}", size, path);

        Ok(ObjectMetadata {
            key: key.to_string(),
            size_bytes: size,
            content_type: None,
            etag: None,
            last_modified: Some(chrono::Utc::now().to_rfc3339()),
        })
    }

    async fn put_file(&self, key: &str, local_path: &Path) -> Result<ObjectMetadata> {
        let dest_path = self.get_full_path(key);

        if let Some(parent) = dest_path.parent() {
            fs::create_dir_all(parent).await?;
        }

        fs::copy(local_path, &dest_path).await?;

        let metadata = fs::metadata(&dest_path).await?;
        
        Ok(ObjectMetadata {
            key: key.to_string(),
            size_bytes: metadata.len(),
            content_type: None,
            etag: None,
            last_modified: Some(chrono::Utc::now().to_rfc3339()),
        })
    }

    async fn get(&self, key: &str) -> Result<Bytes> {
        let path = self.get_full_path(key);
        let mut file = File::open(&path).await?;
        let mut data = Vec::new();
        file.read_to_end(&mut data).await?;
        Ok(Bytes::from(data))
    }

    async fn get_file(&self, key: &str, local_path: &Path) -> Result<()> {
        let src_path = self.get_full_path(key);

        if let Some(parent) = local_path.parent() {
            fs::create_dir_all(parent).await?;
        }

        fs::copy(&src_path, local_path).await?;
        Ok(())
    }

    async fn exists(&self, key: &str) -> Result<bool> {
        let path = self.get_full_path(key);
        Ok(path.exists())
    }

    async fn delete(&self, key: &str) -> Result<()> {
        let path = self.get_full_path(key);
        if path.exists() {
            fs::remove_file(&path).await?;
        }
        Ok(())
    }

    async fn list(&self, prefix: &str) -> Result<Vec<ObjectMetadata>> {
        let path = self.get_full_path(prefix);
        let mut results = Vec::new();

        if !path.exists() {
            return Ok(results);
        }

        let mut entries = fs::read_dir(&path).await?;
        while let Some(entry) = entries.next_entry().await? {
            let metadata = entry.metadata().await?;
            if metadata.is_file() {
                results.push(ObjectMetadata {
                    key: entry.path().to_string_lossy().to_string(),
                    size_bytes: metadata.len(),
                    content_type: None,
                    etag: None,
                    last_modified: None,
                });
            }
        }

        Ok(results)
    }

    async fn metadata(&self, key: &str) -> Result<ObjectMetadata> {
        let path = self.get_full_path(key);
        let metadata = fs::metadata(&path).await?;
        
        Ok(ObjectMetadata {
            key: key.to_string(),
            size_bytes: metadata.len(),
            content_type: None,
            etag: None,
            last_modified: None,
        })
    }

    fn backend_type(&self) -> &str {
        "local"
    }
}

/// AWS S3 storage backend (requires 's3' feature)
#[cfg(feature = "s3")]
pub struct S3Storage {
    client: aws_sdk_s3::Client,
    bucket: String,
    key_prefix: String,
}

#[cfg(feature = "s3")]
impl S3Storage {
    pub async fn new(config: &StorageConfig) -> Result<Self> {
        let bucket = config.s3_bucket.clone().ok_or_else(|| {
            ScraperError::ConfigError("S3 bucket name required".to_string())
        })?;

        let mut aws_config = aws_config::defaults(aws_config::BehaviorVersion::latest());
        
        if let Some(ref region) = config.s3_region {
            aws_config = aws_config.region(aws_config::Region::new(region.clone()));
        }

        let sdk_config = aws_config.load().await;
        
        let mut s3_config = aws_sdk_s3::config::Builder::from(&sdk_config);
        
        if let Some(ref endpoint) = config.s3_endpoint {
            s3_config = s3_config.endpoint_url(endpoint);
        }

        let client = aws_sdk_s3::Client::from_conf(s3_config.build());

        Ok(Self {
            client,
            bucket,
            key_prefix: config.key_prefix.clone(),
        })
    }

    fn full_key(&self, key: &str) -> String {
        format!("{}{}", self.key_prefix, key)
    }
}

#[cfg(feature = "s3")]
#[async_trait]
impl StorageBackend for S3Storage {
    async fn put(&self, key: &str, data: Bytes) -> Result<ObjectMetadata> {
        let full_key = self.full_key(key);
        let size = data.len() as u64;

        self.client
            .put_object()
            .bucket(&self.bucket)
            .key(&full_key)
            .body(data.into())
            .send()
            .await
            .map_err(|e| ScraperError::S3Error(e.to_string()))?;

        info!("Stored {} bytes to S3: s3://{}/{}", size, self.bucket, full_key);

        Ok(ObjectMetadata {
            key: full_key,
            size_bytes: size,
            content_type: None,
            etag: None,
            last_modified: Some(chrono::Utc::now().to_rfc3339()),
        })
    }

    async fn put_file(&self, key: &str, local_path: &Path) -> Result<ObjectMetadata> {
        let data = fs::read(local_path).await?;
        self.put(key, Bytes::from(data)).await
    }

    async fn get(&self, key: &str) -> Result<Bytes> {
        let full_key = self.full_key(key);

        let response = self.client
            .get_object()
            .bucket(&self.bucket)
            .key(&full_key)
            .send()
            .await
            .map_err(|e| ScraperError::S3Error(e.to_string()))?;

        let data = response.body.collect().await
            .map_err(|e| ScraperError::S3Error(e.to_string()))?;
        
        Ok(data.into_bytes())
    }

    async fn get_file(&self, key: &str, local_path: &Path) -> Result<()> {
        let data = self.get(key).await?;
        
        if let Some(parent) = local_path.parent() {
            fs::create_dir_all(parent).await?;
        }

        fs::write(local_path, data).await?;
        Ok(())
    }

    async fn exists(&self, key: &str) -> Result<bool> {
        let full_key = self.full_key(key);

        match self.client
            .head_object()
            .bucket(&self.bucket)
            .key(&full_key)
            .send()
            .await
        {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }

    async fn delete(&self, key: &str) -> Result<()> {
        let full_key = self.full_key(key);

        self.client
            .delete_object()
            .bucket(&self.bucket)
            .key(&full_key)
            .send()
            .await
            .map_err(|e| ScraperError::S3Error(e.to_string()))?;

        Ok(())
    }

    async fn list(&self, prefix: &str) -> Result<Vec<ObjectMetadata>> {
        let full_prefix = self.full_key(prefix);
        let mut results = Vec::new();
        let mut continuation_token: Option<String> = None;

        loop {
            let mut request = self.client
                .list_objects_v2()
                .bucket(&self.bucket)
                .prefix(&full_prefix);

            if let Some(token) = continuation_token {
                request = request.continuation_token(token);
            }

            let response = request.send().await
                .map_err(|e| ScraperError::S3Error(e.to_string()))?;

            if let Some(contents) = response.contents {
                for obj in contents {
                    results.push(ObjectMetadata {
                        key: obj.key.unwrap_or_default(),
                        size_bytes: obj.size.unwrap_or(0) as u64,
                        content_type: None,
                        etag: obj.e_tag,
                        last_modified: obj.last_modified.map(|d| d.to_string()),
                    });
                }
            }

            if response.is_truncated.unwrap_or(false) {
                continuation_token = response.next_continuation_token;
            } else {
                break;
            }
        }

        Ok(results)
    }

    async fn metadata(&self, key: &str) -> Result<ObjectMetadata> {
        let full_key = self.full_key(key);

        let response = self.client
            .head_object()
            .bucket(&self.bucket)
            .key(&full_key)
            .send()
            .await
            .map_err(|e| ScraperError::S3Error(e.to_string()))?;

        Ok(ObjectMetadata {
            key: full_key,
            size_bytes: response.content_length.unwrap_or(0) as u64,
            content_type: response.content_type,
            etag: response.e_tag,
            last_modified: response.last_modified.map(|d| d.to_string()),
        })
    }

    fn backend_type(&self) -> &str {
        "s3"
    }
}

/// Storage manager that abstracts over different backends
pub struct StorageManager {
    backend: Arc<dyn StorageBackend>,
}

impl StorageManager {
    /// Create a new storage manager with the given configuration
    pub async fn new(config: &StorageConfig) -> Result<Self> {
        let backend: Arc<dyn StorageBackend> = match config.backend.as_str() {
            "local" => Arc::new(LocalStorage::new(&config.local_path)?),
            #[cfg(feature = "s3")]
            "s3" => Arc::new(S3Storage::new(config).await?),
            #[cfg(not(feature = "s3"))]
            "s3" => {
                return Err(ScraperError::ConfigError(
                    "S3 storage requires the 's3' feature to be enabled".to_string()
                ))
            }
            #[cfg(feature = "gcs")]
            "gcs" => {
                return Err(ScraperError::ConfigError(
                    "GCS storage not yet implemented".to_string()
                ))
            }
            #[cfg(not(feature = "gcs"))]
            "gcs" => {
                return Err(ScraperError::ConfigError(
                    "GCS storage requires the 'gcs' feature to be enabled".to_string()
                ))
            }
            _ => {
                return Err(ScraperError::ConfigError(format!(
                    "Unknown storage backend: {}",
                    config.backend
                )))
            }
        };

        Ok(Self { backend })
    }

    /// Get the underlying storage backend
    pub fn backend(&self) -> &dyn StorageBackend {
        self.backend.as_ref()
    }
}

/// Python-exposed storage client
#[pyclass]
pub struct PyStorage {
    manager: Arc<tokio::sync::Mutex<Option<StorageManager>>>,
    config: StorageConfig,
    runtime: Arc<tokio::runtime::Runtime>,
}

#[pymethods]
impl PyStorage {
    #[new]
    #[pyo3(signature = (config=None))]
    pub fn new(config: Option<&StorageConfig>) -> PyResult<Self> {
        let config = config.cloned().unwrap_or_default();
        let runtime = tokio::runtime::Runtime::new().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create runtime: {}", e))
        })?;

        Ok(Self {
            manager: Arc::new(tokio::sync::Mutex::new(None)),
            config,
            runtime: Arc::new(runtime),
        })
    }

    /// Initialize the storage backend (must be called before use)
    pub fn initialize(&self) -> PyResult<()> {
        let config = self.config.clone();
        let manager = self.manager.clone();

        self.runtime.block_on(async move {
            let storage = StorageManager::new(&config).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })?;
            
            let mut guard = manager.lock().await;
            *guard = Some(storage);
            Ok(())
        })
    }

    /// Store bytes at the given key
    pub fn put(&self, key: &str, data: Vec<u8>) -> PyResult<ObjectMetadata> {
        let manager = self.manager.clone();
        let key = key.to_string();

        self.runtime.block_on(async move {
            let guard = manager.lock().await;
            let storage = guard.as_ref().ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("Storage not initialized")
            })?;

            storage.backend().put(&key, Bytes::from(data)).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Store a local file
    pub fn put_file(&self, key: &str, local_path: &str) -> PyResult<ObjectMetadata> {
        let manager = self.manager.clone();
        let key = key.to_string();
        let path = PathBuf::from(local_path);

        self.runtime.block_on(async move {
            let guard = manager.lock().await;
            let storage = guard.as_ref().ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("Storage not initialized")
            })?;

            storage.backend().put_file(&key, &path).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Get bytes for a key
    pub fn get(&self, key: &str) -> PyResult<Vec<u8>> {
        let manager = self.manager.clone();
        let key = key.to_string();

        self.runtime.block_on(async move {
            let guard = manager.lock().await;
            let storage = guard.as_ref().ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("Storage not initialized")
            })?;

            storage.backend().get(&key).await
                .map(|b| b.to_vec())
                .map_err(|e| {
                    pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
                })
        })
    }

    /// Download to a local file
    pub fn get_file(&self, key: &str, local_path: &str) -> PyResult<()> {
        let manager = self.manager.clone();
        let key = key.to_string();
        let path = PathBuf::from(local_path);

        self.runtime.block_on(async move {
            let guard = manager.lock().await;
            let storage = guard.as_ref().ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("Storage not initialized")
            })?;

            storage.backend().get_file(&key, &path).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Check if a key exists
    pub fn exists(&self, key: &str) -> PyResult<bool> {
        let manager = self.manager.clone();
        let key = key.to_string();

        self.runtime.block_on(async move {
            let guard = manager.lock().await;
            let storage = guard.as_ref().ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("Storage not initialized")
            })?;

            storage.backend().exists(&key).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// Delete an object
    pub fn delete(&self, key: &str) -> PyResult<()> {
        let manager = self.manager.clone();
        let key = key.to_string();

        self.runtime.block_on(async move {
            let guard = manager.lock().await;
            let storage = guard.as_ref().ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("Storage not initialized")
            })?;

            storage.backend().delete(&key).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }

    /// List objects with a prefix
    pub fn list(&self, prefix: &str) -> PyResult<Vec<ObjectMetadata>> {
        let manager = self.manager.clone();
        let prefix = prefix.to_string();

        self.runtime.block_on(async move {
            let guard = manager.lock().await;
            let storage = guard.as_ref().ok_or_else(|| {
                pyo3::exceptions::PyRuntimeError::new_err("Storage not initialized")
            })?;

            storage.backend().list(&prefix).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
            })
        })
    }
}
