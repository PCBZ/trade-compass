#!/bin/bash
set -e

PROJECT_ID=$(grep gcp_project_id compute_engine/terraform.tfvars | cut -d'"' -f2)
BUCKET="trade-compass-tfstate-${PROJECT_ID}"

echo "=== Step 1: Bootstrap (GCS bucket) ==="
cd bootstrap
terraform init
terraform apply -auto-approve -var="gcp_project_id=${PROJECT_ID}"
cd ..

echo "=== Step 2: Compute Engine ==="
cd compute_engine
terraform init -backend-config="bucket=${BUCKET}" -backend-config="prefix=compute_engine"
terraform apply -auto-approve
cd ..

echo "=== Step 3: Atlas ==="
cd atlas
terraform init -backend-config="bucket=${BUCKET}" -backend-config="prefix=atlas"
terraform apply -auto-approve -var="tfstate_bucket=${BUCKET}"
cd ..

echo "=== Done ==="
