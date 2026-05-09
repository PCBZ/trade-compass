output "instance_name" {
  description = "Compute Engine instance name"
  value       = google_compute_instance.trade_compass.name
}

output "external_ip" {
  description = "Static external IP — automatically read by atlas module"
  value       = google_compute_address.trade_compass.address
}

output "service_account_email" {
  description = "Service account email"
  value       = google_service_account.trade_compass.email
}
