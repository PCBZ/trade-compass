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

variable "telegram_bot_token" {
  description = "Telegram bot token from BotFather"
  type        = string
  sensitive   = true
}

variable "telegram_chat_id" {
  description = "Telegram chat ID to send push notifications to"
  type        = string
  sensitive   = true
}

variable "fmp_api_key" {
  description = "Financial Modeling Prep API key"
  type        = string
  sensitive   = true
}

variable "openrouter_api_key" {
  description = "OpenRouter API key for LLM access"
  type        = string
  sensitive   = true
}

variable "sec_contact" {
  description = "Contact email declared to SEC EDGAR; it returns 403 without one"
  type        = string
  default     = ""
}
