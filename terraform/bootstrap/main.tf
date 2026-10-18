terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.11"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = "us-west1"
}

# ── Enable required GCP APIs ──────────────────────────────────
resource "google_project_service" "apis" {
  for_each = toset([
    "secretmanager.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "storage.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudscheduler.googleapis.com",
    "bigquery.googleapis.com",
    "logging.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false

  # Enabling a service needs the role granted below; wait for it to propagate.
  depends_on = [time_sleep.serviceusage_grant]
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

  depends_on = [google_project_service.apis]
}

# ── Deployer permissions ──────────────────────────────────────
# The CD service account's own roles, as code. DEPLOY.md carried this list in
# prose and had already drifted: roles/viewer was granted by hand and never
# written down.
#
# These are additive `_member` bindings, so they leave any other members on a
# role untouched. Applied by its own CD job ahead of the deploys, because
# granting a role and consuming it in the same apply races IAM propagation.
locals {
  deployer = "serviceAccount:gh-deployer@${var.gcp_project_id}.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "deployer" {
  for_each = toset([
    "artifactregistry.admin",
    "bigquery.admin", # create the eval dataset, set its IAM
    "cloudbuild.builds.editor",
    "iam.serviceAccountAdmin",
    "iam.serviceAccountUser",
    "logging.configWriter", # create the decision log sink
    "resourcemanager.projectIamAdmin",
    "run.admin",
    "secretmanager.admin",
    "serviceusage.serviceUsageAdmin", # enable the APIs above
    "storage.admin",
    "viewer", # Cloud Build log streaming
  ])

  project = var.gcp_project_id
  role    = "roles/${each.value}"
  member  = local.deployer
}

# IAM is eventually consistent, and this is the one grant used within the same
# apply that creates it.
resource "time_sleep" "serviceusage_grant" {
  create_duration = "120s"

  depends_on = [google_project_iam_member.deployer["serviceusage.serviceUsageAdmin"]]
}
