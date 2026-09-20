# CutPilot AI — API and worker image (shared; the command decides the role)
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg/ffprobe for media processing; libgl for OpenCV; fonts for caption burn-in
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 fonts-dejavu-core fonts-inter curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api/pyproject.toml /app/pyproject.toml
COPY apps/api/cutpilot/__init__.py /app/cutpilot/__init__.py
RUN pip install --upgrade pip && pip install -e ".[dev,local-transcription]"

COPY apps/api /app

RUN mkdir -p /data/storage /data/work && chmod +x /app/scripts/*.sh

EXPOSE 8000
CMD ["/app/scripts/start-api.sh"]
