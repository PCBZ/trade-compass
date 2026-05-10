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

locals {
  image = "${var.region}-docker.pkg.dev/${var.gcp_project_id}/${google_artifact_registry_repository.api.repository_id}/api:latest"
}

# ── Build and push image ──────────────────────────────────────
resource "null_resource" "build_push" {
  triggers = {
    src_hash = sha1(join("", [
      for f in sort(fileset("${path.root}/../../api", "**")) :
      filesha1("${path.root}/../../api/${f}")
    ]))
  }

  provisioner "local-exec" {
    command = "docker build --platform linux/amd64 -t ${local.image} ${path.root}/../../api && docker push ${local.image}"
  }

  depends_on = [google_artifact_registry_repository.api]
}

# ── Service account ───────────────────────────────────────────
resource "google_service_account" "api" {
  account_id   = "trade-compass-api"
  display_name = "trade-compass API Cloud Run SA"
}

# ── Secret: MongoDB URI ───────────────────────────────────────
resource "google_secret_manager_secret" "mongodb_uri" {
  secret_id = "trade-compass-mongodb-uri"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "api_secret_access" {
  secret_id = google_secret_manager_secret.mongodb_uri.id
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

      resources {
        limits = {
          memory = "512Mi"
          cpu    = "1"
        }
      }
    }
  }

  depends_on = [null_resource.build_push, google_secret_manager_secret_iam_member.api_secret_access]
}

# ── Allow unauthenticated (API key auth added in task #7) ─────
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
