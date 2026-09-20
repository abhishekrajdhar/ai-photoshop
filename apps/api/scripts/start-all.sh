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
celery -A cutpilot.workers.celery_app:celery_app worker --loglevel="${LOG_LEVEL:-INFO}" -Q media,render,ai \
  --concurrency="${WORKER_CONCURRENCY:-2}" --max-tasks-per-child=25 -n "all-in-one@%h" &
WORKER_PID=$!
trap 'kill $WORKER_PID 2>/dev/null || true' EXIT
echo "[all-in-one] starting api on :${PORT:-8000}"
exec uvicorn cutpilot.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${UVICORN_WORKERS:-1}" --proxy-headers --forwarded-allow-ips="*"
