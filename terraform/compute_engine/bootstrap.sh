#!/bin/bash
set -euo pipefail

export HOME=/root
export DEBIAN_FRONTEND=noninteractive

# ── System setup ──────────────────────────────────────────────
apt-get update -y
apt-get install -y python3 python3-pip python3-venv curl wget unzip apt-transport-https ca-certificates gnupg

# ── Install Google Cloud CLI ──────────────────────────────────
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list
apt-get update -y
apt-get install -y google-cloud-cli

# ── Create app directories ────────────────────────────────────
mkdir -p /opt/trade-compass/sync
mkdir -p /opt/futu-opend

# ── Read instance metadata ────────────────────────────────────
METADATA_BASE="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
METADATA_HEADER="Metadata-Flavor: Google"

SYNC_BUCKET=$(curl -sf -H "${METADATA_HEADER}" "${METADATA_BASE}/trade-compass-sync-bucket")

# ── Download sync scripts from GCS ───────────────────────────
BUCKET="gs://${SYNC_BUCKET}"
gsutil cp "${BUCKET}/sync/main.py" /opt/trade-compass/sync/
gsutil cp "${BUCKET}/sync/setup_cron.sh" /opt/trade-compass/sync/
gsutil cp "${BUCKET}/sync/requirements.txt" /opt/trade-compass/sync/
chmod +x /opt/trade-compass/sync/setup_cron.sh

# ── Python venv + dependencies ────────────────────────────────
python3 -m venv /opt/trade-compass/venv
/opt/trade-compass/venv/bin/pip install --upgrade pip
/opt/trade-compass/venv/bin/pip install -r /opt/trade-compass/sync/requirements.txt

# ── Download Moomoo OpenD (Ubuntu 18.04 build, compatible with 24.04) ────
OPEND_URL="https://softwaredownload.futustatic.com/moomoo_OpenD_10.7.6718_Ubuntu18.04.tar.gz"

wget -q "${OPEND_URL}" -O /tmp/FutuOpenD.tar.gz
tar -xzf /tmp/FutuOpenD.tar.gz -C /opt/futu-opend --strip-components=1
rm /tmp/FutuOpenD.tar.gz

# ── Read config and secrets → write .env ─────────────────────
API_URL_VAL=$(curl -sf -H "${METADATA_HEADER}" "${METADATA_BASE}/trade-compass-api-url")
API_KEY_VAL=$(gcloud secrets versions access latest --secret=trade-compass-api-key)

cat > /opt/trade-compass/sync/.env <<EOF
OPEND_HOST=127.0.0.1
OPEND_PORT=11111
API_URL=${API_URL_VAL}
API_KEY=${API_KEY_VAL}
EOF
chmod 600 /opt/trade-compass/sync/.env

# ── Locate OpenD binary (version-agnostic) ────────────────────
OPEND_BIN=$(find /opt/futu-opend -name "OpenD" -type f | head -1)
OPEND_DIR=$(dirname "${OPEND_BIN}")
OPEND_XML="${OPEND_DIR}/OpenD.xml"
chmod +x "${OPEND_BIN}"

# ── systemd service for OpenD ─────────────────────────────────
cat > /etc/systemd/system/moomoo-opend.service <<EOF
[Unit]
Description=Moomoo OpenD
After=network.target

[Service]
Environment="LD_LIBRARY_PATH=${OPEND_DIR}"
ExecStart=${OPEND_BIN} -cfg ${OPEND_XML}
WorkingDirectory=${OPEND_DIR}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable moomoo-opend

echo "=== Bootstrap complete ==="
echo "Next step: edit ${OPEND_XML} with Moomoo credentials, then:"
echo "  systemctl start futu-opend"
echo "  bash /opt/trade-compass/sync/setup_cron.sh"
