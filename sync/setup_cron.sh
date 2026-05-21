#!/bin/bash
# Set up cron job to sync Moomoo positions during US market hours.
# US market: 9:30-16:00 ET = 13:30-20:00 UTC
# Runs every 5 minutes during market hours, Mon-Fri.
# Three cron entries: 13:30-13:55, 14:00-19:55, and exactly 20:00 UTC.

set -e

VENV="/opt/trade-compass/venv"
SCRIPT="/opt/trade-compass/sync/main.py"
LOG="/var/log/trade-compass-sync.log"

# 13:30-13:55 UTC (first half hour of market open)
CRON_JOB_1="30,35,40,45,50,55 13 * * 1-5 ${VENV}/bin/python ${SCRIPT} >> ${LOG} 2>&1"
# 14:00-19:55 UTC
CRON_JOB_2="*/5 14-19 * * 1-5 ${VENV}/bin/python ${SCRIPT} >> ${LOG} 2>&1"
# 20:00 UTC exactly (market close)
CRON_JOB_3="0 20 * * 1-5 ${VENV}/bin/python ${SCRIPT} >> ${LOG} 2>&1"

# Filter old entries first, then append new ones
EXISTING=$(crontab -l 2>/dev/null || true)
(echo "${EXISTING}" | grep -v "${SCRIPT}" || true; echo "${CRON_JOB_1}"; echo "${CRON_JOB_2}"; echo "${CRON_JOB_3}") | crontab -

echo "Cron job installed:"
crontab -l | grep "${SCRIPT}"
