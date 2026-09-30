#!/usr/bin/env bash
# All-in-one entrypoint for single-container hosts (Render/Railway/Fly): Redis + workers + API.
# Media is stored on the mounted disk (LOCAL_STORAGE_ROOT); use STORAGE_PROVIDER=s3 for multi-instance setups.
set -euo pipefail
cd /app
mkdir -p "${LOCAL_STORAGE_ROOT:-/data/storage}" "${WORK_DIR:-/data/work}" /data/redis
if [ -z "${REDIS_URL:-}" ] || [[ "${REDIS_URL}" == redis://localhost* ]] || [[ "${REDIS_URL}" == redis://127.0.0.1* ]]; then
  export REDIS_URL="redis://127.0.0.1:6379/0"
  echo "[all-in-one] starting embedded redis"
  redis-server --port 6379 --bind 127.0.0.1 --dir /data/redis --save "" --appendonly no --maxmemory "${REDIS_MAXMEMORY:-128mb}" --maxmemory-policy allkeys-lru --daemonize yes
fi
echo "[all-in-one] waiting for database…"
python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from cutpilot.core.config import get_settings
for _ in range(60):
    try:
        with create_engine(get_settings().sync_database_url).connect() as c:
            c.execute(text("select 1")); sys.exit(0)
    except Exception:
        time.sleep(2)
print("database not reachable", file=sys.stderr); sys.exit(1)
PY
echo "[all-in-one] running migrations…"
alembic upgrade head
echo "[all-in-one] starting workers…"
# prefork (default) isolates tasks; WORKER_POOL=threads = one process, for 512 MB hosts
POOL="${WORKER_POOL:-prefork}"; POOL_ARGS=()
[ "$POOL" = "prefork" ] && POOL_ARGS=(--max-tasks-per-child=25)
# Supervised: if the worker is OOM-killed, fail the jobs it was running and start a fresh one.
(
  while true; do
    celery -A cutpilot.workers.celery_app:celery_app worker --loglevel="${LOG_LEVEL:-INFO}" -Q media,render,ai \
      -P "$POOL" --concurrency="${WORKER_CONCURRENCY:-2}" "${POOL_ARGS[@]}" -n "all-in-one@%h" && code=0 || code=$?
    echo "[all-in-one] worker exited (code $code); failing orphaned jobs and restarting in 3s"
    python -m cutpilot.workers.maintenance fail-orphans || true
    sleep 3
  done
) &
SUPERVISOR_PID=$!
trap 'kill $SUPERVISOR_PID 2>/dev/null || true; pkill -f "celery -A cutpilot" 2>/dev/null || true' EXIT
echo "[all-in-one] starting api on :${PORT:-8000}"
exec uvicorn cutpilot.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${UVICORN_WORKERS:-1}" --proxy-headers --forwarded-allow-ips="*"
