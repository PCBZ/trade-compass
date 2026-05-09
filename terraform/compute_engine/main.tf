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

# ── Service account ───────────────────────────────────────────
resource "google_service_account" "trade_compass" {
  account_id   = "trade-compass-vm"
  display_name = "trade-compass Compute Engine SA"
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
    enable-oslogin = "TRUE"
  }

  metadata_startup_script = file("${path.module}/bootstrap.sh")

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
  }
}
