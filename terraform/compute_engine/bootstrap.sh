#!/bin/bash
set -e

export HOME=/root
export DEBIAN_FRONTEND=noninteractive

# ── System setup ──────────────────────────────────────────────
apt-get update -y
apt-get install -y python3 python3-pip python3-venv curl wget

# ── Python venv + futu-api ────────────────────────────────────
python3 -m venv /opt/trade-compass/venv
/opt/trade-compass/venv/bin/pip install --upgrade pip
/opt/trade-compass/venv/bin/pip install futu-api

# ── Create app directory ──────────────────────────────────────
mkdir -p /opt/trade-compass/sync

echo "=== Bootstrap complete ==="
echo "Next: install Futu OpenD manually and complete one-time login"
