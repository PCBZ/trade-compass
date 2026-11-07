#!/bin/bash
# Set up the cron job that syncs Moomoo positions during US market hours.
#
# US market hours are 9:30-16:00 Eastern, which is 13:30-20:00 UTC in daylight
# time and 14:30-21:00 UTC in standard time. Cron runs in UTC here, so it fires
# every 5 minutes across 13:30-21:00 UTC, Mon-Fri, covering both; main.py then
# skips any firing outside the session in Eastern time, and market holidays.

set -e

VENV="/opt/trade-compass/venv"
SCRIPT="/opt/trade-compass/sync/main.py"
LOG="/var/log/trade-compass-sync.log"

# 13:30-13:55 UTC
CRON_JOB_1="30,35,40,45,50,55 13 * * 1-5 ${VENV}/bin/python ${SCRIPT} >> ${LOG} 2>&1"
# 14:00-20:55 UTC
CRON_JOB_2="*/5 14-20 * * 1-5 ${VENV}/bin/python ${SCRIPT} >> ${LOG} 2>&1"
# 21:00 UTC exactly (the close, in standard time)
CRON_JOB_3="0 21 * * 1-5 ${VENV}/bin/python ${SCRIPT} >> ${LOG} 2>&1"

# Filter old entries first, then append new ones
EXISTING=$(crontab -l 2>/dev/null || true)
(echo "${EXISTING}" | grep -v "${SCRIPT}" || true; echo "${CRON_JOB_1}"; echo "${CRON_JOB_2}"; echo "${CRON_JOB_3}") | crontab -

echo "Cron job installed:"
crontab -l | grep "${SCRIPT}"
