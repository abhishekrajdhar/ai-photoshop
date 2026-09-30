"""Worker housekeeping: `python -m cutpilot.workers.maintenance fail-orphans`.

Run after a worker process dies (e.g. OOM-killed): jobs it was executing stay RUNNING forever
otherwise, and the UI would wait on them indefinitely.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from cutpilot.db.models.jobs import Export, Job, Render
from cutpilot.db.session import get_sync_session_factory

log = structlog.get_logger()

ORPHAN_ERROR = "Worker restarted while this job was running (likely out of memory). Retry the step."


def fail_orphaned_jobs() -> int:
    """Mark every RUNNING job FAILED. Only call this when no worker is alive."""
    with get_sync_session_factory()() as session:
        jobs = list(session.scalars(select(Job).where(Job.status == "RUNNING")))
        now = datetime.now(UTC)
        for job in jobs:
            job.status = "FAILED"
            job.error = ORPHAN_ERROR
            job.completed_at = now
            # rows the UI polls instead of the job itself
            for model in (Render, Export):
                for row in session.scalars(select(model).where(model.job_id == job.id)):
                    if row.status in ("QUEUED", "RUNNING"):
                        row.status = "FAILED"
                        row.error = ORPHAN_ERROR
        session.commit()
    if jobs:
        log.warning("orphaned_jobs_failed", count=len(jobs), ids=[str(j.id) for j in jobs])
    return len(jobs)


def main(argv: list[str]) -> int:
    if argv[:1] == ["fail-orphans"]:
        print(f"failed {fail_orphaned_jobs()} orphaned job(s)")
        return 0
    print("usage: python -m cutpilot.workers.maintenance fail-orphans", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
