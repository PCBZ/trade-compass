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
  description = "Database user for the REST API"
  type        = string
  default     = "trade-compass-api"
}

variable "db_password" {
  description = "Database user password (must not contain URI reserved characters: @:/?#[]!$&'()*+,;=)"
  type        = string
  sensitive   = true

  validation {
    condition     = !can(regex("[@:/?#\\[\\]!$&'()*+,;=%]", var.db_password))
    error_message = "db_password must not contain URI reserved characters (@:/?#[]!$&'()*+,;=%). Use alphanumeric and - _ . characters only."
  }
}

variable "tfstate_bucket" {
  description = "GCS bucket name for Terraform remote state (from bootstrap output)"
  type        = string
}
