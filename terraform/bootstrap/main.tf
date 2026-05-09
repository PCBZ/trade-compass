terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = "us-west1"
}

# ── GCS bucket for Terraform remote state ─────────────────────
resource "google_storage_bucket" "tfstate" {
  name          = "trade-compass-tfstate-${var.gcp_project_id}"
  location      = "US-WEST1"
  force_destroy = false

  versioning {
    enabled = true
  }

  uniform_bucket_level_access = true
}
