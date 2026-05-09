output "instance_name" {
  description = "Compute Engine instance name"
  value       = google_compute_instance.trade_compass.name
}

output "external_ip" {
  description = "External IP of the instance — add this to Atlas allowed_ips"
  value       = google_compute_instance.trade_compass.network_interface[0].access_config[0].nat_ip
}

output "service_account_email" {
  description = "Service account email"
  value       = google_service_account.trade_compass.email
}
