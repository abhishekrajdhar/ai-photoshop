from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from cutpilot.api.deps import CurrentUser, DBSession, OwnedProject, ai_rate_limit, rate_limit
from cutpilot.api.routes.timeline import _state
from cutpilot.schemas.chat import (
    ChatMessageOut,
    ChatSendRequest,
    ChatSendResponse,
    ChatSessionOut,
    EditRequest,
    ProposalApplyOut,
    ProposalPreviewOut,
)
from cutpilot.services import chat_service as svc
from cutpilot.services.events import publish_async

router = APIRouter(
    prefix="/projects/{project_id}", tags=["chat"], dependencies=[Depends(rate_limit)]
)


@router.get("/chat/sessions", response_model=list[ChatSessionOut])
async def list_sessions(project: OwnedProject, db: DBSession) -> list[ChatSessionOut]:
    return [ChatSessionOut.model_validate(s) for s in await svc.list_sessions(db, project)]


@router.post("/chat/sessions", response_model=ChatSessionOut, status_code=201)
async def create_session(project: OwnedProject, user: CurrentUser, db: DBSession) -> ChatSessionOut:
    return ChatSessionOut.model_validate(await svc.create_session(db, project, user))


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionOut)
async def get_session(
    session_id: uuid.UUID, project: OwnedProject, user: CurrentUser, db: DBSession
) -> ChatSessionOut:
    return ChatSessionOut.model_validate(
        await svc.get_or_create_session(db, project, user, session_id)
    )


@router.post("/chat", response_model=ChatSendResponse, dependencies=[Depends(ai_rate_limit)])
async def send_message(
    body: ChatSendRequest, project: OwnedProject, user: CurrentUser, db: DBSession
) -> ChatSendResponse:
    session = await svc.get_or_create_session(db, project, user, body.session_id)
    user_msg, assistant, job_id = await svc.send_message(
        db,
        project=project,
        user=user,
        session=session,
        text=body.message,
        asset_id=body.asset_id,
        timeline_id=body.timeline_id,
    )
    session = await svc.get_or_create_session(db, project, user, session.id)
    return ChatSendResponse(
        session=ChatSessionOut.model_validate(session),
        user_message=ChatMessageOut.model_validate(user_msg),
        assistant_message=ChatMessageOut.model_validate(assistant),
        job_id=job_id,
    )


@router.post("/edit", response_model=ChatSendResponse, dependencies=[Depends(ai_rate_limit)])
async def request_edit(
    body: EditRequest, project: OwnedProject, user: CurrentUser, db: DBSession
) -> ChatSendResponse:
    session, user_msg, assistant, job_id = await svc.request_edit(
        db,
        project=project,
        user=user,
        instruction=body.instruction,
        target_platform=body.target_platform,
        target_duration=body.target_duration_seconds,
        asset_id=body.asset_id,
        timeline_id=body.timeline_id,
    )
    return ChatSendResponse(
        session=ChatSessionOut.model_validate(session),
        user_message=ChatMessageOut.model_validate(user_msg),
        assistant_message=ChatMessageOut.model_validate(assistant),
        job_id=job_id,
    )


@router.get("/chat/messages/{message_id}", response_model=ChatMessageOut)
async def get_message(
    message_id: uuid.UUID, project: OwnedProject, db: DBSession
) -> ChatMessageOut:
    return ChatMessageOut.model_validate(await svc.get_message(db, project, message_id))


@router.post("/chat/messages/{message_id}/preview", response_model=ProposalPreviewOut)
async def preview_proposal(
    message_id: uuid.UUID, project: OwnedProject, db: DBSession
) -> ProposalPreviewOut:
    msg = await svc.get_message(db, project, message_id)
    return ProposalPreviewOut(**await svc.preview_proposal(db, project, msg))


@router.post("/chat/messages/{message_id}/apply", response_model=ProposalApplyOut)
async def apply_proposal(
    message_id: uuid.UUID, project: OwnedProject, user: CurrentUser, db: DBSession
) -> ProposalApplyOut:
    msg = await svc.get_message(db, project, message_id)
    timeline, version, jobs = await svc.apply_proposal(db, project, user, msg)
    await publish_async(
        "timeline.updated",
        {
            "timeline_id": str(timeline.id),
            "version_id": str(version.id) if version else None,
            "source": "ai",
        },
        project_id=project.id,
    )
    return ProposalApplyOut(
        state=await _state(db, timeline, version),
        message=ChatMessageOut.model_validate(msg),
        jobs=jobs,
    )


@router.post("/chat/messages/{message_id}/reject", response_model=ChatMessageOut)
async def reject_proposal(
    message_id: uuid.UUID, project: OwnedProject, db: DBSession
) -> ChatMessageOut:
    msg = await svc.get_message(db, project, message_id)
    return ChatMessageOut.model_validate(await svc.reject_proposal(db, msg))
