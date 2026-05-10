output "service_url" {
  description = "Cloud Run service URL"
  value       = google_cloud_run_v2_service.api.uri
}

output "api_key" {
  description = "Generated API key for X-API-Key header"
  value       = random_password.api_key.result
  sensitive   = true
}
