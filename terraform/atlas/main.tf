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
  backing_provider_name       = "GCP"
  provider_region_name        = "US_EAST_4"
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

# ── IP access list ────────────────────────────────────────────
resource "mongodbatlas_project_ip_access_list" "allowed" {
  for_each   = toset(var.allowed_ips)
  project_id = mongodbatlas_project.trade_compass.id
  ip_address = each.value
  comment    = "Allowed IP"
}
