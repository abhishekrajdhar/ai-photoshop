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


# ── memory watchdog (threads/solo pools) ─────────────────────────────────────
# Celery's --max-memory-per-child only exists for prefork. On 512 MB hosts the single worker
# process slowly grows (OpenCV, PySceneDetect, SDKs, heap fragmentation) until the next ffmpeg
# child pushes the container over the limit. After each task, if RSS exceeds WORKER_MAX_RSS_MB
# we ask for a warm shutdown; the all-in-one supervisor starts a fresh ~100 MB worker.


def _rss_mb() -> float:
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


if settings.worker_max_rss_mb > 0:
    from celery.signals import task_postrun

    @task_postrun.connect(weak=False)
    def _recycle_if_bloated(**_: object) -> None:
        import os
        import signal

        import structlog

        rss = _rss_mb()
        if rss > settings.worker_max_rss_mb:
            structlog.get_logger().warning(
                "worker_recycle", rss_mb=round(rss), limit_mb=settings.worker_max_rss_mb
            )
            os.kill(os.getpid(), signal.SIGTERM)  # warm shutdown: finish acks, then exit 0
