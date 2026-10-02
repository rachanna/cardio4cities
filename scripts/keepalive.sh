#!/bin/sh
# Calls the public health endpoint (LLD-4 §7). Render's c4c-keepalive cron runs the same
# request every 6 hours; run this by hand to check a deployment:
#   sh scripts/keepalive.sh https://c4c-app.onrender.com
set -e
URL="${1:-$APP_HEALTH_URL}"
[ -n "$URL" ] || { echo "usage: keepalive.sh <base URL>" >&2; exit 2; }
curl -fsS --retry 3 --retry-delay 10 --max-time 30 "${URL%/}/api/v1/health"
echo
