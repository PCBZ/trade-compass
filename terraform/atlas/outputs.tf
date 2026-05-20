output "connection_string" {
  description = "MongoDB Atlas connection string (use with db_username / db_password)"
  value       = mongodbatlas_cluster.main.connection_strings[0].standard_srv
  sensitive   = true
}

output "mongodb_uri" {
  description = "Full MongoDB connection URI including credentials"
  value = replace(
    mongodbatlas_cluster.main.connection_strings[0].standard_srv,
    "mongodb+srv://",
    "mongodb+srv://${var.db_username}:${var.db_password}@"
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
