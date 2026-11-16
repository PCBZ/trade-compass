#!/bin/bash
# Set up the cron jobs that run during US market hours: the position sync
# (main.py) and the paper-trading executor (execute.py, #87).
#
# US market hours are 9:30-16:00 Eastern, which is 13:30-20:00 UTC in daylight
# time and 14:30-21:00 UTC in standard time. Cron runs in UTC here, so it fires
# every 5 minutes across 13:30-21:00 UTC, Mon-Fri, covering both; each script
# then skips any firing outside the session in Eastern time, and market
# holidays. They are separate jobs so one failing never stops the other, and
# the executor holds a lock, so a slow run is never overlapped by the next.

set -e

VENV="/opt/trade-compass/venv"
DIR="/opt/trade-compass/sync"

# The session schedule, shared by both jobs (tests/test_market_hours.py checks
# that it covers every 5-minute slot of the session in both time regimes).
# 13:30-13:55 UTC
SESSION_SCHEDULE_1="30,35,40,45,50,55 13 * * 1-5"
# 14:00-20:55 UTC
SESSION_SCHEDULE_2="*/5 14-20 * * 1-5"
# 21:00 UTC exactly (the close, in standard time)
SESSION_SCHEDULE_3="0 21 * * 1-5"

session_jobs() {
  local script="$1" log="$2"
  for schedule in "${SESSION_SCHEDULE_1}" "${SESSION_SCHEDULE_2}" "${SESSION_SCHEDULE_3}"; do
    echo "${schedule} ${VENV}/bin/python ${script} >> ${log} 2>&1"
  done
}

# Filter old entries first, then append new ones
EXISTING=$(crontab -l 2>/dev/null || true)
(
  echo "${EXISTING}" | grep -v -e "${DIR}/main.py" -e "${DIR}/execute.py" || true
  session_jobs "${DIR}/main.py" /var/log/trade-compass-sync.log
  session_jobs "${DIR}/execute.py" /var/log/trade-compass-execute.log
) | crontab -

echo "Cron jobs installed:"
crontab -l | grep "${DIR}/"
