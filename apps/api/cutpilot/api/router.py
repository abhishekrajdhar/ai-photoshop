from __future__ import annotations

from fastapi import APIRouter

from cutpilot.api.routes import auth, events, jobs, projects, timeline

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(timeline.router)
api_router.include_router(jobs.router)
api_router.include_router(events.router)
