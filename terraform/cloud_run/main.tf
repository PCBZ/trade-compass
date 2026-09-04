terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.11"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.region
}

# ── Artifact Registry ─────────────────────────────────────────
resource "google_artifact_registry_repository" "api" {
  repository_id = "trade-compass"
  format        = "DOCKER"
  location      = var.region
}

# ── Grant Cloud Build SA storage + logging access ─────────────────────────────
# GCP (2024+) uses the Compute Engine default SA for Cloud Build in new projects.
locals {
  src_hash      = sha1(join("", [for f in sort(fileset("${path.root}/../../api", "**")) : filesha1("${path.root}/../../api/${f}")]))
  image         = "${var.region}-docker.pkg.dev/${var.gcp_project_id}/${google_artifact_registry_repository.api.repository_id}/api:${local.src_hash}"
  cloudbuild_sa = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

resource "google_project_iam_member" "cloudbuild_storage" {
  project = var.gcp_project_id
  role    = "roles/storage.objectAdmin"
  member  = local.cloudbuild_sa
}

resource "google_project_iam_member" "cloudbuild_logs" {
  project = var.gcp_project_id
  role    = "roles/logging.logWriter"
  member  = local.cloudbuild_sa
}

resource "google_project_iam_member" "cloudbuild_ar_writer" {
  project = var.gcp_project_id
  role    = "roles/artifactregistry.writer"
  member  = local.cloudbuild_sa
}

data "google_project" "project" {
  project_id = var.gcp_project_id
}

# ── Wait for IAM to propagate before building ────────────────────────────────
resource "time_sleep" "iam_propagation" {
  create_duration = "90s"

  depends_on = [
    google_project_iam_member.cloudbuild_storage,
    google_project_iam_member.cloudbuild_logs,
    google_project_iam_member.cloudbuild_ar_writer,
  ]
}

# ── Build and push image via Cloud Build (no local Docker needed) ─────────────
resource "null_resource" "build_push" {
  triggers = {
    src_hash = local.src_hash
  }

  provisioner "local-exec" {
    command = "gcloud builds submit ${path.root}/../../api --tag ${local.image} --project ${var.gcp_project_id}"
  }

  depends_on = [
    google_artifact_registry_repository.api,
    time_sleep.iam_propagation,
  ]
}

# ── Service account ───────────────────────────────────────────
resource "google_service_account" "api" {
  account_id   = "trade-compass-api"
  display_name = "trade-compass API Cloud Run SA"
}

resource "google_artifact_registry_repository_iam_member" "api_image_pull" {
  location   = var.region
  repository = google_artifact_registry_repository.api.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.api.email}"
}

# ── Remote state: read Atlas outputs ─────────────────────────
data "terraform_remote_state" "atlas" {
  backend = "gcs"
  config = {
    bucket = coalesce(var.tfstate_bucket, "trade-compass-tfstate-${var.gcp_project_id}")
    prefix = "atlas"
  }
}

# ── Secret: MongoDB URI ───────────────────────────────────────
resource "google_secret_manager_secret" "mongodb_uri" {
  secret_id = "trade-compass-mongodb-uri"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "mongodb_uri" {
  secret      = google_secret_manager_secret.mongodb_uri.id
  secret_data = data.terraform_remote_state.atlas.outputs.mongodb_uri
}

# ── Secret: API Key ───────────────────────────────────────────
resource "random_password" "api_key" {
  length  = 32
  special = false
}

resource "google_secret_manager_secret" "api_key" {
  secret_id = "trade-compass-api-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "api_key" {
  secret      = google_secret_manager_secret.api_key.id
  secret_data = random_password.api_key.result
}

resource "google_secret_manager_secret_iam_member" "api_secret_access" {
  secret_id = google_secret_manager_secret.mongodb_uri.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "api_key_access" {
  secret_id = google_secret_manager_secret.api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

# ── Cloud Run service ─────────────────────────────────────────
resource "google_cloud_run_v2_service" "api" {
  name     = "trade-compass-api"
  location = var.region

  template {
    service_account = google_service_account.api.email

    containers {
      image = local.image

      env {
        name = "MONGODB_URI"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.mongodb_uri.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_key.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          memory = "512Mi"
          cpu    = "1"
        }
      }
    }
  }

  lifecycle {
    # CI/CD deploys new images with `gcloud run deploy`, so the running image is
    # owned by the pipeline, not this state. Without this, the next `terraform
    # apply` would revert the service to the image its src_hash last built.
    ignore_changes = [template[0].containers[0].image]
  }

  depends_on = [
    null_resource.build_push,
    google_secret_manager_secret_iam_member.api_secret_access,
    google_secret_manager_secret_iam_member.api_key_access,
    google_secret_manager_secret_version.mongodb_uri,
    google_secret_manager_secret_version.api_key,
  ]
}

# ── Allow unauthenticated (auth handled by X-API-Key header) ──
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
