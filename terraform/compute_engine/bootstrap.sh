#!/bin/bash
set -e

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

# ── Download sync scripts from GCS ───────────────────────────
PROJECT_ID=$(curl -sf -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/project/project-id")

gsutil cp "gs://trade-compass-tfstate-${PROJECT_ID}/sync/*" /opt/trade-compass/sync/
chmod +x /opt/trade-compass/sync/setup_cron.sh

# ── Python venv + dependencies ────────────────────────────────
python3 -m venv /opt/trade-compass/venv
/opt/trade-compass/venv/bin/pip install --upgrade pip
/opt/trade-compass/venv/bin/pip install -r /opt/trade-compass/sync/requirements.txt

# ── Download Moomoo OpenD (Ubuntu 18.04 build, compatible with 24.04) ────
wget -q "https://softwaredownload.futustatic.com/moomoo_OpenD_10.5.6508_Ubuntu18.04.tar.gz" -O /tmp/FutuOpenD.tar.gz
tar -xzf /tmp/FutuOpenD.tar.gz -C /opt/futu-opend --strip-components=1
rm /tmp/FutuOpenD.tar.gz

# ── Read config and secrets → write .env ─────────────────────
METADATA_BASE="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
METADATA_HEADER="Metadata-Flavor: Google"

API_URL_VAL=$(curl -sf -H "${METADATA_HEADER}" "${METADATA_BASE}/trade-compass-api-url")
API_KEY_VAL=$(gcloud secrets versions access latest --secret=trade-compass-api-key)

cat > /opt/trade-compass/sync/.env <<EOF
OPEND_HOST=127.0.0.1
OPEND_PORT=11111
API_URL=${API_URL_VAL}
API_KEY=${API_KEY_VAL}
EOF
chmod 600 /opt/trade-compass/sync/.env

# ── systemd service for OpenD ─────────────────────────────────
cat > /etc/systemd/system/futu-opend.service <<'EOF'
[Unit]
Description=Futu OpenD
After=network.target

[Service]
ExecStart=/opt/futu-opend/FutuOpenD -cfg /opt/futu-opend/FutuOpenD_config.xml
WorkingDirectory=/opt/futu-opend
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable futu-opend

echo "=== Bootstrap complete ==="
echo "Next step: edit /opt/futu-opend/FutuOpenD_config.xml with Moomoo credentials, then:"
echo "  systemctl start futu-opend"
echo "  bash /opt/trade-compass/sync/setup_cron.sh"
