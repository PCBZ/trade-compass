#!/bin/bash
set -euo pipefail

OPEND_URL="https://softwaredownload.futustatic.com/moomoo_OpenD_10.7.6718_Ubuntu18.04.tar.gz"

echo "=== Stopping moomoo-opend ==="
systemctl stop moomoo-opend 2>/dev/null || systemctl stop futu-opend 2>/dev/null || true

echo "=== Downloading Moomoo OpenD ==="
rm -rf /opt/futu-opend/*
rm -f /tmp/FutuOpenD.tar.gz
wget -q "${OPEND_URL}" -O /tmp/FutuOpenD.tar.gz
tar -xzf /tmp/FutuOpenD.tar.gz -C /opt/futu-opend --strip-components=1
rm /tmp/FutuOpenD.tar.gz

echo "=== Configuring systemd service ==="
OPEND_BIN=$(find /opt/futu-opend -name "OpenD" -type f | head -1)
OPEND_DIR=$(dirname "${OPEND_BIN}")
chmod +x "${OPEND_BIN}"

tee /etc/systemd/system/moomoo-opend.service > /dev/null <<EOF
[Unit]
Description=Moomoo OpenD
After=network.target

[Service]
Environment=LD_LIBRARY_PATH=${OPEND_DIR}
ExecStart=${OPEND_BIN} -cfg ${OPEND_DIR}/OpenD.xml
WorkingDirectory=${OPEND_DIR}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable moomoo-opend
systemctl start moomoo-opend

echo "=== Done ==="
sleep 3
systemctl status moomoo-opend | head -8
