#!/usr/bin/env bash
set -euo pipefail
cd /app
echo "[api] waiting for database…"
python - <<'PY'
import time, sys
from sqlalchemy import create_engine, text
from cutpilot.core.config import get_settings
url = get_settings().sync_database_url
for i in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("select 1"))
        sys.exit(0)
    except Exception as e:
        time.sleep(1)
print("database not reachable", file=sys.stderr); sys.exit(1)
PY
echo "[api] running migrations…"
alembic upgrade head
if [ "${APP_ENV:-development}" = "production" ]; then
  exec uvicorn cutpilot.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-2}" --proxy-headers --forwarded-allow-ips="*"
else
  exec uvicorn cutpilot.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/cutpilot
fi
