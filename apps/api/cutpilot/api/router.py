from __future__ import annotations

from fastapi import APIRouter

from cutpilot.api.routes import (
    analysis,
    assets,
    auth,
    chat,
    events,
    jobs,
    projects,
    render,
    timeline,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(timeline.router)
api_router.include_router(assets.router)
api_router.include_router(analysis.router)
api_router.include_router(chat.router)
api_router.include_router(render.router)
api_router.include_router(jobs.router)
api_router.include_router(events.router)
