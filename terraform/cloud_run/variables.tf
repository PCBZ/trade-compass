variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-west1"
}

variable "tfstate_bucket" {
  description = "GCS bucket name for Terraform remote state"
  type        = string
  default     = null
}
