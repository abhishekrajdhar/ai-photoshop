"""Server-Sent Events stream of job / analysis / render progress."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from cutpilot.api.deps import CurrentUser, OwnedProject
from cutpilot.services.events import channel_for_project, channel_for_user, subscribe

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def user_stream(request: Request, user: CurrentUser) -> EventSourceResponse:
    async def gen():  # type: ignore[no-untyped-def]
        async for evt in subscribe([channel_for_user(user.id)]):
            if await request.is_disconnected():
                break
            yield evt

    return EventSourceResponse(gen())


@router.get("/projects/{project_id}")
async def project_stream(
    request: Request, project: OwnedProject, user: CurrentUser
) -> EventSourceResponse:
    project_id: uuid.UUID = project.id

    async def gen():  # type: ignore[no-untyped-def]
        async for evt in subscribe([channel_for_project(project_id), channel_for_user(user.id)]):
            if await request.is_disconnected():
                break
            yield evt

    return EventSourceResponse(gen())
