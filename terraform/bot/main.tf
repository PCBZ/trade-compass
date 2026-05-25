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

data "google_project" "project" {
  project_id = var.gcp_project_id
}

# ── Remote state: read API URL + key from cloud_run ───────────────────────────
data "terraform_remote_state" "cloud_run" {
  backend = "gcs"
  config = {
    bucket = coalesce(var.tfstate_bucket, "trade-compass-tfstate-${var.gcp_project_id}")
    prefix = "cloud_run"
  }
}

# ── Image: reuse existing Artifact Registry repo ──────────────────────────────
locals {
  src_hash      = sha1(join("", [for f in sort(fileset("${path.root}/../../bot/src", "**")) : filesha1("${path.root}/../../bot/src/${f}")]))
  image         = "${var.region}-docker.pkg.dev/${var.gcp_project_id}/trade-compass/bot:${local.src_hash}"
  cloudbuild_sa = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# ── Build and push bot image via Cloud Build ──────────────────────────────────
resource "null_resource" "build_push" {
  triggers = {
    src_hash = local.src_hash
  }

  provisioner "local-exec" {
    command = "gcloud builds submit ${path.root}/../../bot --tag ${local.image} --project ${var.gcp_project_id}"
  }
}

# ── Service account ───────────────────────────────────────────────────────────
resource "google_service_account" "bot" {
  account_id   = "trade-compass-bot"
  display_name = "trade-compass Bot Cloud Run SA"
}

resource "google_artifact_registry_repository_iam_member" "bot_image_pull" {
  location   = var.region
  repository = "trade-compass"
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.bot.email}"
}

# ── Secrets ───────────────────────────────────────────────────────────────────
resource "google_secret_manager_secret" "telegram_bot_token" {
  secret_id = "trade-compass-telegram-bot-token"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "telegram_bot_token" {
  secret      = google_secret_manager_secret.telegram_bot_token.id
  secret_data = var.telegram_bot_token
}

resource "google_secret_manager_secret" "telegram_chat_id" {
  secret_id = "trade-compass-telegram-chat-id"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "telegram_chat_id" {
  secret      = google_secret_manager_secret.telegram_chat_id.id
  secret_data = var.telegram_chat_id
}

resource "google_secret_manager_secret" "fmp_api_key" {
  secret_id = "trade-compass-fmp-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "fmp_api_key" {
  secret      = google_secret_manager_secret.fmp_api_key.id
  secret_data = var.fmp_api_key
}

resource "google_secret_manager_secret" "openrouter_api_key" {
  secret_id = "trade-compass-openrouter-api-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "openrouter_api_key" {
  secret      = google_secret_manager_secret.openrouter_api_key.id
  secret_data = var.openrouter_api_key
}

# ── Grant bot SA access to all secrets ───────────────────────────────────────
locals {
  bot_secrets = [
    google_secret_manager_secret.telegram_bot_token.id,
    google_secret_manager_secret.telegram_chat_id.id,
    google_secret_manager_secret.fmp_api_key.id,
    google_secret_manager_secret.openrouter_api_key.id,
  ]
}

resource "google_secret_manager_secret_iam_member" "bot_secret_access" {
  count     = length(local.bot_secrets)
  secret_id = local.bot_secrets[count.index]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bot.email}"
}

# Also grant access to API key secret (owned by cloud_run module)
resource "google_secret_manager_secret_iam_member" "bot_api_key_access" {
  secret_id = "trade-compass-api-key"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bot.email}"
}

# ── Cloud Run service ─────────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "bot" {
  name     = "trade-compass-bot"
  location = var.region

  template {
    service_account = google_service_account.bot.email

    containers {
      image = local.image

      env {
        name = "TELEGRAM_BOT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.telegram_bot_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "TELEGRAM_CHAT_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.telegram_chat_id.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "FMP_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.fmp_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "OPENROUTER_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.openrouter_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "API_URL"
        value = data.terraform_remote_state.cloud_run.outputs.service_url
      }

      env {
        name = "API_KEY"
        value_source {
          secret_key_ref {
            secret  = "trade-compass-api-key"
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          memory = "1Gi"
          cpu    = "1"
        }
      }
    }
  }

  depends_on = [
    null_resource.build_push,
    google_secret_manager_secret_iam_member.bot_secret_access,
    google_secret_manager_secret_iam_member.bot_api_key_access,
  ]
}

# ── Allow unauthenticated (Telegram webhook needs public access) ──────────────
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.bot.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Cloud Scheduler: 5 daily push notifications ───────────────────────────────
# All times in UTC (ET = UTC-4 in summer, UTC-5 in winter; using UTC-4 / EDT)
# pre_market  09:25 ET → 13:25 UTC
# morning     11:00 ET → 15:00 UTC
# noon        12:30 ET → 16:30 UTC
# afternoon   14:30 ET → 18:30 UTC
# post_market 16:05 ET → 20:05 UTC

locals {
  push_schedules = {
    pre_market  = "25 13 * * 1-5"
    morning     = "0 15 * * 1-5"
    noon        = "30 16 * * 1-5"
    afternoon   = "30 18 * * 1-5"
    post_market = "5 20 * * 1-5"
  }
}

resource "google_cloud_scheduler_job" "push" {
  for_each = local.push_schedules

  name             = "trade-compass-push-${each.key}"
  description      = "trade-compass bot ${each.key} push"
  schedule         = each.value
  time_zone        = "America/New_York"
  attempt_deadline = "180s"

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.bot.uri}/push"
    body        = base64encode(jsonencode({ type = each.key }))
    headers = {
      "Content-Type" = "application/json"
    }
  }

  depends_on = [google_cloud_run_v2_service.bot]
}
