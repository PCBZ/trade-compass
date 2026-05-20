output "connection_string" {
  description = "MongoDB Atlas connection string (use with db_username / db_password)"
  value       = mongodbatlas_cluster.main.connection_strings[0].standard_srv
  sensitive   = true
}

locals {
  # URL-encode special characters in password that would break the URI
  encoded_password = replace(
    replace(
      replace(
        replace(
          replace(var.db_password, "%", "%25"),
          "@", "%40"),
        ":", "%3A"),
      "/", "%2F"),
    "+", "%2B")
}

output "mongodb_uri" {
  description = "Full MongoDB connection URI including credentials"
  value = replace(
    mongodbatlas_cluster.main.connection_strings[0].standard_srv,
    "mongodb+srv://",
    "mongodb+srv://${var.db_username}:${local.encoded_password}@"
  )
  sensitive = true
}

output "project_id" {
  description = "Atlas project ID"
  value       = mongodbatlas_project.trade_compass.id
}

output "cluster_id" {
  description = "Atlas cluster ID"
  value       = mongodbatlas_cluster.main.cluster_id
}
