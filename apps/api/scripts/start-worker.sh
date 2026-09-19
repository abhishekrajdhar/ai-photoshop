#!/usr/bin/env bash
# Usage: start-worker.sh <queues> [concurrency]
set -euo pipefail
cd /app
QUEUES="${1:-media,ai,render}"
CONCURRENCY="${2:-${WORKER_CONCURRENCY:-2}}"
exec celery -A cutpilot.workers.celery_app:celery_app worker \
  --loglevel="${LOG_LEVEL:-INFO}" -Q "$QUEUES" --concurrency="$CONCURRENCY" \
  --max-tasks-per-child=50 -n "worker-${QUEUES//,/-}@%h"
