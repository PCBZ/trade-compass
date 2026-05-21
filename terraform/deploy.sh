#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "${SCRIPT_DIR}")"

if [ ! -f "${ROOT_DIR}/.env" ]; then
  echo "Error: .env file not found at repo root."
  exit 1
fi
# shellcheck source=/dev/null
source "${ROOT_DIR}/.env"
PROJECT_ID=${GCP_PROJECT_ID:?"GCP_PROJECT_ID is not set in .env"}
BUCKET="trade-compass-tfstate-${PROJECT_ID}"

echo "=== Step 1: Bootstrap (GCS bucket) ==="
cd bootstrap
terraform init
terraform apply -auto-approve -var="gcp_project_id=${PROJECT_ID}"
cd ..

echo "=== Step 2: Compute Engine (static IP only — no api_url yet) ==="
cd compute_engine
terraform init -backend-config="bucket=${BUCKET}" -backend-config="prefix=compute_engine"
terraform apply -auto-approve -var="gcp_project_id=${PROJECT_ID}" -var="tfstate_bucket=${BUCKET}"
cd ..

echo "=== Step 3: Atlas ==="
cd atlas
terraform init -backend-config="bucket=${BUCKET}" -backend-config="prefix=atlas"
terraform apply -auto-approve -var="tfstate_bucket=${BUCKET}"
cd ..

echo "=== Step 4: Cloud Run ==="
cd cloud_run
terraform init -backend-config="bucket=${BUCKET}" -backend-config="prefix=cloud_run"
terraform apply -auto-approve -var="gcp_project_id=${PROJECT_ID}" -var="tfstate_bucket=${BUCKET}"
API_URL=$(terraform output -raw service_url)
cd ..

echo "=== Step 5: Compute Engine (update with api_url) ==="
cd compute_engine
terraform apply -auto-approve -var="gcp_project_id=${PROJECT_ID}" -var="tfstate_bucket=${BUCKET}" -var="api_url=${API_URL}"
cd ..

echo "=== Step 6: Generate bot/.env ==="
API_KEY=$(cd cloud_run && terraform output -raw api_key)
cat > "${ROOT_DIR}/bot/.env" <<EOF
API_URL=${API_URL}
API_KEY=${API_KEY}
FMP_API_KEY=
OPENROUTER_API_KEY=
TELEGRAM_BOT_TOKEN=
EOF
echo "bot/.env written (FMP_API_KEY / OPENROUTER_API_KEY / TELEGRAM_BOT_TOKEN still need to be filled in)"

echo "=== Done ==="
