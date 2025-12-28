# VideoScraper GCP Infrastructure
# Terraform configuration for scalable video scraping

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "proxy_username" {
  description = "Proxy service username"
  type        = string
  sensitive   = true
}

variable "proxy_password" {
  description = "Proxy service password"
  type        = string
  sensitive   = true
}

variable "proxy_provider" {
  description = "Proxy provider (brightdata, oxylabs, smartproxy)"
  type        = string
  default     = "brightdata"
}

variable "max_instances" {
  description = "Maximum Cloud Run instances"
  type        = number
  default     = 100
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "cloudscheduler.googleapis.com",
  ])
  
  service = each.value
  disable_on_destroy = false
}

# GCS Bucket for video storage
resource "google_storage_bucket" "videos" {
  name     = "videoscraper-${var.project_id}"
  location = var.region
  
  uniform_bucket_level_access = true
  
  lifecycle_rule {
    condition {
      age = 90  # Move to coldline after 90 days
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }
  
  lifecycle_rule {
    condition {
      age = 365  # Delete after 1 year
    }
    action {
      type = "Delete"
    }
  }
}

# Secret Manager for proxy credentials
resource "google_secret_manager_secret" "proxy_username" {
  secret_id = "proxy-username"
  
  replication {
    auto {}
  }
  
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "proxy_username" {
  secret      = google_secret_manager_secret.proxy_username.id
  secret_data = var.proxy_username
}

resource "google_secret_manager_secret" "proxy_password" {
  secret_id = "proxy-password"
  
  replication {
    auto {}
  }
  
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "proxy_password" {
  secret      = google_secret_manager_secret.proxy_password.id
  secret_data = var.proxy_password
}

# Pub/Sub topic for URL distribution
resource "google_pubsub_topic" "scrape_urls" {
  name = "scrape-urls"
  
  depends_on = [google_project_service.apis]
}

# Dead letter topic
resource "google_pubsub_topic" "deadletter" {
  name = "scrape-urls-deadletter"
  
  depends_on = [google_project_service.apis]
}

# Results topic
resource "google_pubsub_topic" "results" {
  name = "scrape-results"
  
  depends_on = [google_project_service.apis]
}

# Service account for Cloud Run
resource "google_service_account" "worker" {
  account_id   = "videoscraper-worker"
  display_name = "VideoScraper Worker"
}

# Grant permissions
resource "google_project_iam_member" "worker_storage" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "worker_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_secrets" {
  for_each = {
    username = google_secret_manager_secret.proxy_username.id
    password = google_secret_manager_secret.proxy_password.id
  }
  
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

# Cloud Run service
resource "google_cloud_run_v2_service" "worker" {
  name     = "videoscraper-worker"
  location = var.region
  
  template {
    service_account = google_service_account.worker.email
    
    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }
    
    containers {
      image = "gcr.io/${var.project_id}/videoscraper-worker"
      
      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
      }
      
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.videos.name
      }
      
      env {
        name  = "PROXY_PROVIDER"
        value = var.proxy_provider
      }
      
      env {
        name = "PROXY_USERNAME"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.proxy_username.secret_id
            version = "latest"
          }
        }
      }
      
      env {
        name = "PROXY_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.proxy_password.secret_id
            version = "latest"
          }
        }
      }
    }
  }
  
  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.proxy_username,
    google_secret_manager_secret_version.proxy_password,
  ]
}

# Pub/Sub subscription to Cloud Run
resource "google_pubsub_subscription" "worker" {
  name  = "scrape-urls-push"
  topic = google_pubsub_topic.scrape_urls.id
  
  push_config {
    push_endpoint = google_cloud_run_v2_service.worker.uri
    
    oidc_token {
      service_account_email = google_service_account.worker.email
    }
  }
  
  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"  # 7 days
  
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.deadletter.id
    max_delivery_attempts = 5
  }
  
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

# Multi-region deployment (optional - uncomment for geo-distribution)
# resource "google_cloud_run_v2_service" "worker_eu" {
#   name     = "videoscraper-worker"
#   location = "europe-west1"
#   # ... same config ...
# }

# resource "google_cloud_run_v2_service" "worker_asia" {
#   name     = "videoscraper-worker"
#   location = "asia-east1"
#   # ... same config ...
# }

# Outputs
output "service_url" {
  value = google_cloud_run_v2_service.worker.uri
}

output "bucket_name" {
  value = google_storage_bucket.videos.name
}

output "topic_name" {
  value = google_pubsub_topic.scrape_urls.name
}

