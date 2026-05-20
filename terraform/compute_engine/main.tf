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
  region  = var.region
  zone    = var.zone
}

# ── Remote state: read Cloud Run outputs ──────────────────────
data "terraform_remote_state" "cloud_run" {
  backend = "gcs"
  config = {
    bucket = "trade-compass-tfstate-${var.gcp_project_id}"
    prefix = "cloud_run"
  }
}

# ── Secret Manager: look up api_key secret ────────────────────
data "google_secret_manager_secret" "api_key" {
  secret_id = "trade-compass-api-key"
}

# ── Service account ───────────────────────────────────────────
resource "google_service_account" "trade_compass" {
  account_id   = "trade-compass-vm"
  display_name = "trade-compass Compute Engine SA"
}

# ── Grant VM SA access to api_key secret ──────────────────────
resource "google_secret_manager_secret_iam_member" "vm_api_key_access" {
  secret_id = data.google_secret_manager_secret.api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.trade_compass.email}"
}

# ── Upload sync scripts to GCS ────────────────────────────────
locals {
  sync_files = ["main.py", "setup_cron.sh", "requirements.txt"]
}

resource "google_storage_bucket_object" "sync" {
  for_each = toset(local.sync_files)
  name     = "sync/${each.value}"
  bucket   = "trade-compass-tfstate-${var.gcp_project_id}"
  source   = "${path.module}/../../sync/${each.value}"
}

# ── Grant VM SA read access to GCS bucket ────────────────────
resource "google_storage_bucket_iam_member" "vm_sync_read" {
  bucket = "trade-compass-tfstate-${var.gcp_project_id}"
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.trade_compass.email}"
}

# ── Firewall: allow SSH ───────────────────────────────────────
resource "google_compute_firewall" "allow_ssh" {
  name    = "trade-compass-allow-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = var.ssh_allowed_ips
  target_tags   = ["trade-compass"]
}

# ── Static external IP ────────────────────────────────────────
resource "google_compute_address" "trade_compass" {
  name   = "trade-compass-ip"
  region = var.region
}

# ── Compute Engine instance (e2-micro, free tier) ─────────────
resource "google_compute_instance" "trade_compass" {
  name         = "trade-compass"
  machine_type = "e2-micro"
  tags         = ["trade-compass"]

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
      size  = 30
      type  = "pd-standard"
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.trade_compass.address
    }
  }

  service_account {
    email  = google_service_account.trade_compass.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin        = "TRUE"
    trade-compass-api-url = data.terraform_remote_state.cloud_run.outputs.service_url
  }

  depends_on = [
    google_secret_manager_secret_iam_member.vm_api_key_access,
    google_storage_bucket_iam_member.vm_sync_read,
    google_storage_bucket_object.sync,
  ]

  metadata_startup_script = file("${path.module}/bootstrap.sh")

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }
}
