terraform {
  # Run: terraform init -backend-config="bucket=trade-compass-tfstate-YOUR_GCP_PROJECT_ID" -backend-config="prefix=cloud_run"
  backend "gcs" {}
}
