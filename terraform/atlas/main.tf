terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "~> 1.15"
    }
  }
}

provider "mongodbatlas" {
  public_key  = var.atlas_public_key
  private_key = var.atlas_private_key
}

# ── Read compute_engine state to get static IP ────────────────
data "terraform_remote_state" "compute_engine" {
  backend = "gcs"
  config = {
    bucket = var.tfstate_bucket
    prefix = "compute_engine"
  }
}


# ── Project ───────────────────────────────────────────────────
resource "mongodbatlas_project" "trade_compass" {
  name   = var.project_name
  org_id = var.atlas_org_id
}

# ── Cluster (M0 free tier) ────────────────────────────────────
resource "mongodbatlas_cluster" "main" {
  project_id = mongodbatlas_project.trade_compass.id
  name       = "trade-compass"

  provider_name               = "TENANT"
  backing_provider_name       = "AWS"
  provider_region_name        = "US_WEST_2"
  provider_instance_size_name = "M0"
}

# ── Database user ─────────────────────────────────────────────
resource "mongodbatlas_database_user" "api" {
  project_id         = mongodbatlas_project.trade_compass.id
  username           = var.db_username
  password           = var.db_password
  auth_database_name = "admin"

  roles {
    role_name     = "readWrite"
    database_name = "trade_compass"
  }
}

# ── IP access list (auto-read from compute_engine state) ──────
resource "mongodbatlas_project_ip_access_list" "compute_engine" {
  project_id = mongodbatlas_project.trade_compass.id
  ip_address = data.terraform_remote_state.compute_engine.outputs.external_ip
  comment    = "Compute Engine static IP"
}

# M0 free tier does not support VPC peering or private endpoints.
# Real security is the credentials stored in Secret Manager.
resource "mongodbatlas_project_ip_access_list" "cloud_run" {
  project_id = mongodbatlas_project.trade_compass.id
  cidr_block = "0.0.0.0/0"
  comment    = "Cloud Run egress — M0 does not support VPC peering; auth via Secret Manager"
}
