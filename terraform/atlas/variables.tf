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
  description = "Database user password"
  type        = string
  sensitive   = true
}

variable "allowed_ips" {
  description = "List of IPs allowed to connect to Atlas (GCP VM + Cloud Run egress IPs)"
  type        = list(string)
  default     = []
}
