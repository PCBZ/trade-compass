variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-west1"
}

variable "zone" {
  description = "GCP zone"
  type        = string
  default     = "us-west1-b"
}

variable "ssh_allowed_ips" {
  description = "CIDR ranges allowed to SSH into the instance"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
