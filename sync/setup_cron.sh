#!/bin/bash
# Set up cron job to sync Moomoo positions during US market hours.
# US market: 9:30-16:00 ET = 13:30-20:00 UTC
# Runs every 5 minutes during market hours, Mon-Fri.

set -e

VENV="/opt/trade-compass/venv"
SCRIPT="/opt/trade-compass/sync/main.py"
LOG="/var/log/trade-compass-sync.log"

CRON_JOB="*/5 13-19 * * 1-5 ${VENV}/bin/python ${SCRIPT} >> ${LOG} 2>&1"

(crontab -l 2>/dev/null | grep -v "${SCRIPT}"; echo "${CRON_JOB}") | crontab -

echo "Cron job installed:"
crontab -l | grep "${SCRIPT}"
