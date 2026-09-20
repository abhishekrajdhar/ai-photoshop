# Hugging Face Space / single-container deployment: Redis + API + workers in one image.
# (Docker Compose uses infrastructure/docker/*.Dockerfile; this root Dockerfile exists because
#  Docker Spaces require it here.)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/user PATH=/home/user/.local/bin:$PATH \
    LOCAL_STORAGE_ROOT=/data/storage WORK_DIR=/data/work STORAGE_PROVIDER=local APP_ENV=production PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 fonts-dejavu-core fonts-inter curl redis-server \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user && mkdir -p /app /data && chown -R user:user /app /data

WORKDIR /app
COPY --chown=user:user apps/api/pyproject.toml /app/pyproject.toml
COPY --chown=user:user apps/api/cutpilot/__init__.py /app/cutpilot/__init__.py
RUN pip install --upgrade pip && pip install -e ".[dev,local-transcription]"
COPY --chown=user:user apps/api /app
RUN chmod +x /app/scripts/*.sh

USER user
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD curl -fsS http://localhost:7860/api/health || exit 1
CMD ["/app/scripts/start-all.sh"]
