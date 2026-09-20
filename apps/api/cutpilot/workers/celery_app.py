"""Celery application. Queues: media (ffmpeg-heavy), ai (LLM/ASR), render (final encodes)."""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from cutpilot.core.config import get_settings
from cutpilot.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, json_output=settings.is_production)

celery_app = Celery("cutpilot", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    task_queues=(Queue("media"), Queue("ai"), Queue("render")),
    task_default_queue="media",
    task_routes={
        "cutpilot.workers.tasks.media.*": {"queue": "media"},
        "cutpilot.workers.tasks.analysis.*": {"queue": "ai"},
        "cutpilot.workers.tasks.ai.*": {"queue": "ai"},
        "cutpilot.workers.tasks.render.*": {"queue": "render"},
    },
    # Tests run tasks inline.
    task_always_eager=settings.app_env == "test",
    task_eager_propagates=settings.app_env == "test",
    imports=(
        "cutpilot.workers.tasks.media",
        "cutpilot.workers.tasks.analysis",
        "cutpilot.workers.tasks.ai",
        "cutpilot.workers.tasks.render",
    ),
)
