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

echo "=== Step 6: Update bot/.env with terraform outputs ==="
API_KEY=$(cd cloud_run && terraform output -raw api_key)
ENV_FILE="${ROOT_DIR}/bot/.env"

# Helper: set or replace a key in bot/.env, preserving all other lines.
# Portable (macOS + Linux): rewrites file via temp file instead of sed -i.
# Values are written as-is via printf to avoid sed special-char issues.
set_env() {
  local key="$1" val="$2"
  local tmp
  tmp="$(mktemp)"
  if grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null; then
    # Copy every line except the matching key, then append updated key=val
    grep -v "^${key}=" "${ENV_FILE}" > "${tmp}"
    printf '%s=%s\n' "${key}" "${val}" >> "${tmp}"
  else
    cp "${ENV_FILE}" "${tmp}"
    printf '%s=%s\n' "${key}" "${val}" >> "${tmp}"
  fi
  mv "${tmp}" "${ENV_FILE}"
}

touch "${ENV_FILE}"
set_env "API_URL"  "${API_URL}"
set_env "API_KEY"  "${API_KEY}"

# Only add placeholder lines if key is not already present
grep -q "^FMP_API_KEY=" "${ENV_FILE}"         || echo "FMP_API_KEY="         >> "${ENV_FILE}"
grep -q "^OPENROUTER_API_KEY=" "${ENV_FILE}"  || echo "OPENROUTER_API_KEY="  >> "${ENV_FILE}"
grep -q "^TELEGRAM_BOT_TOKEN=" "${ENV_FILE}"  || echo "TELEGRAM_BOT_TOKEN="  >> "${ENV_FILE}"
grep -q "^TELEGRAM_CHAT_ID=" "${ENV_FILE}"    || echo "TELEGRAM_CHAT_ID="    >> "${ENV_FILE}"

echo "bot/.env updated (API_URL + API_KEY refreshed; existing keys preserved)"

echo "=== Step 7: Bot Cloud Run ==="
cd bot
terraform init -backend-config="bucket=${BUCKET}" -backend-config="prefix=bot"
terraform apply -auto-approve \
  -var="gcp_project_id=${PROJECT_ID}" \
  -var="tfstate_bucket=${BUCKET}" \
  -var="telegram_bot_token=$(grep '^TELEGRAM_BOT_TOKEN=' "${ROOT_DIR}/bot/.env" | cut -d= -f2-)" \
  -var="telegram_chat_id=$(grep '^TELEGRAM_CHAT_ID=' "${ROOT_DIR}/bot/.env" | cut -d= -f2-)" \
  -var="fmp_api_key=$(grep '^FMP_API_KEY=' "${ROOT_DIR}/bot/.env" | cut -d= -f2-)" \
  -var="openrouter_api_key=$(grep '^OPENROUTER_API_KEY=' "${ROOT_DIR}/bot/.env" | cut -d= -f2-)"
BOT_URL=$(terraform output -raw bot_url)
cd ..

echo "=== Step 8: Register Telegram webhook ==="
TELEGRAM_BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "${ROOT_DIR}/bot/.env" | cut -d= -f2-)

# Wait for bot Cloud Run to be healthy before registering webhook
echo "  Waiting for bot service to be healthy..."
for i in $(seq 1 12); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BOT_URL}/health" 2>/dev/null || echo "000")
  if [ "${STATUS}" = "200" ]; then
    echo "  Bot service is healthy (attempt ${i})"
    break
  fi
  echo "  Attempt ${i}/12: status=${STATUS}, retrying in 10s..."
  sleep 10
done

# Token is passed in the URL path (Telegram API requirement), but we avoid
# echoing the full URL to logs to reduce accidental token exposure.
WEBHOOK_RESP=$(curl -s \
  --url "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${BOT_URL}/webhook")
if echo "${WEBHOOK_RESP}" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('ok') else 1)"; then
  echo "  Webhook registered: ${BOT_URL}/webhook"
else
  echo "  WARNING: webhook registration may have failed"
  echo "  Response: ${WEBHOOK_RESP}"
fi

echo "=== Done ==="
echo ""
echo "  API URL : ${API_URL}"
echo "  Bot URL : ${BOT_URL}"
