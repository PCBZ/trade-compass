variable "atlas_public_key" {
  description = "MongoDB Atlas API public key"
  type        = string
  sensitive   = true
}

variable "atlas_private_key" {
  description = "MongoDB Atlas API private key"
  type        = string
  sensitive   = true
}

variable "atlas_org_id" {
  description = "MongoDB Atlas organization ID"
  type        = string
}

variable "project_name" {
  description = "Atlas project name"
  type        = string
  default     = "trade-compass"
}

variable "db_username" {
  description = "Database user for the REST API (alphanumeric and - _ . only)"
  type        = string
  default     = "trade-compass-api"

  validation {
    condition     = can(regex("^[a-zA-Z0-9._-]+$", var.db_username))
    error_message = "db_username must contain only alphanumeric characters and - _ . to ensure a valid MongoDB URI."
  }
}

variable "db_password" {
  description = "Database user password (alphanumeric and - _ . only)"
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[a-zA-Z0-9._-]+$", var.db_password))
    error_message = "db_password must contain only alphanumeric characters and - _ . to ensure a valid MongoDB URI."
  }
}

variable "tfstate_bucket" {
  description = "GCS bucket name for Terraform remote state (from bootstrap output)"
  type        = string
}
