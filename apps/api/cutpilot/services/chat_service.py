"""Chat sessions, proposals, and dispatch of chat/edit jobs to the AI worker."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cutpilot.core.errors import NotFoundError, ValidationFailed
from cutpilot.db.models import ChatMessage, ChatSession, Project, Timeline, User
from cutpilot.services import job_service
from cutpilot.services import timeline_service as ts
from cutpilot.timeline.engine import apply_operations
from cutpilot.timeline.operations import EditOperation


async def reload_session(db: AsyncSession, session_id: uuid.UUID) -> ChatSession:
    """Re-read a session with fresh messages (bypasses the identity map's cached collection)."""
    return (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.id == session_id)
            .options(selectinload(ChatSession.messages))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def get_or_create_session(
    db: AsyncSession, project: Project, user: User, session_id: uuid.UUID | None
) -> ChatSession:
    if session_id is not None:
        s = (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.id == session_id)
                .options(selectinload(ChatSession.messages))
            )
        ).scalar_one_or_none()
        if s is None or s.project_id != project.id:
            raise NotFoundError("Chat session not found")
        return s
    s = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.project_id == project.id)
                .options(selectinload(ChatSession.messages))
                .order_by(ChatSession.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if s is None:
        s = ChatSession(project_id=project.id, user_id=user.id, title="Editing chat")
        db.add(s)
        await db.commit()
        s = (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.id == s.id)
                .options(selectinload(ChatSession.messages))
            )
        ).scalar_one()
    return s


async def list_sessions(db: AsyncSession, project: Project) -> list[ChatSession]:
    rows = (
        (
            await db.execute(
                select(ChatSession)
                .where(ChatSession.project_id == project.id)
                .options(selectinload(ChatSession.messages))
                .order_by(ChatSession.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def create_session(
    db: AsyncSession, project: Project, user: User, title: str = "New chat"
) -> ChatSession:
    s = ChatSession(project_id=project.id, user_id=user.id, title=title)
    db.add(s)
    await db.commit()
    return (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.id == s.id)
            .options(selectinload(ChatSession.messages))
        )
    ).scalar_one()


async def send_message(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    session: ChatSession,
    text: str,
    asset_id: uuid.UUID | None,
    timeline_id: uuid.UUID | None,
) -> tuple[ChatMessage, ChatMessage, uuid.UUID]:
    from cutpilot.services.analysis_service import primary_source_asset
    from cutpilot.workers.tasks.ai import run_chat_task

    asset = await primary_source_asset(db, project, asset_id)
    timeline = await ts.get_timeline(db, project, timeline_id)
    user_msg = ChatMessage(session_id=session.id, role="user", content=text.strip())
    db.add(user_msg)
    await db.flush()
    assistant = ChatMessage(
        session_id=session.id,
        role="assistant",
        content="",
        proposal={
            "status": "pending",
            "summary": "",
            "operations": [],
            "estimated_duration_delta": None,
            "warnings": [],
        },
    )
    db.add(assistant)
    if not session.title or session.title in ("Editing chat", "New chat"):
        session.title = text.strip()[:60]
    await db.commit()
    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="EDIT_PLANNING",
        meta={
            "kind": "chat",
            "session_id": str(session.id),
            "message_id": str(assistant.id),
            "asset_id": str(asset.id),
            "timeline_id": str(timeline.id),
        },
        max_retries=0,
    )
    assistant.job_id = job.id
    await db.commit()
    task = run_chat_task.apply_async(
        kwargs={
            "job_id": str(job.id),
            "message_id": str(assistant.id),
            "asset_id": str(asset.id),
            "timeline_id": str(timeline.id),
        },
        queue="ai",
    )
    job.celery_task_id = task.id
    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(assistant)
    return user_msg, assistant, job.id


async def request_edit(
    db: AsyncSession,
    *,
    project: Project,
    user: User,
    instruction: str,
    target_platform: str | None,
    target_duration: float | None,
    asset_id: uuid.UUID | None,
    timeline_id: uuid.UUID | None,
) -> tuple[ChatSession, ChatMessage, ChatMessage, uuid.UUID]:
    """Direct planner run (POST /edit): produces a proposal message in the default session."""
    from cutpilot.services.analysis_service import primary_source_asset
    from cutpilot.workers.tasks.ai import plan_edit_task

    asset = await primary_source_asset(db, project, asset_id)
    timeline = await ts.get_timeline(db, project, timeline_id)
    session = await get_or_create_session(db, project, user, None)
    user_msg = ChatMessage(session_id=session.id, role="user", content=instruction.strip())
    db.add(user_msg)
    assistant = ChatMessage(
        session_id=session.id,
        role="assistant",
        content="",
        proposal={
            "status": "pending",
            "summary": "",
            "operations": [],
            "estimated_duration_delta": None,
            "warnings": [],
        },
    )
    db.add(assistant)
    await db.commit()
    job = await job_service.create_job(
        db,
        user_id=user.id,
        project_id=project.id,
        job_type="EDIT_PLANNING",
        meta={
            "kind": "plan",
            "session_id": str(session.id),
            "message_id": str(assistant.id),
            "asset_id": str(asset.id),
            "timeline_id": str(timeline.id),
        },
        max_retries=0,
    )
    assistant.job_id = job.id
    await db.commit()
    task = plan_edit_task.apply_async(
        kwargs={
            "job_id": str(job.id),
            "message_id": str(assistant.id),
            "asset_id": str(asset.id),
            "timeline_id": str(timeline.id),
            "instruction": instruction,
            "target_platform": target_platform,
            "target_duration": target_duration,
        },
        queue="ai",
    )
    job.celery_task_id = task.id
    await db.commit()
    session = await reload_session(db, session.id)
    await db.refresh(assistant)
    await db.refresh(user_msg)
    return session, user_msg, assistant, job.id


async def get_message(db: AsyncSession, project: Project, message_id: uuid.UUID) -> ChatMessage:
    msg = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.id == message_id)
            .options(selectinload(ChatMessage.session))
        )
    ).scalar_one_or_none()
    if msg is None or msg.session.project_id != project.id:
        raise NotFoundError("Message not found")
    return msg


def _proposal_ops(msg: ChatMessage) -> list[EditOperation]:
    proposal = msg.proposal or {}
    ops = [EditOperation.model_validate(o) for o in proposal.get("operations", [])]
    return ops


def removed_ranges(ops: list[EditOperation]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for op in ops:
        if op.type in ("remove_segment", "silence_removal", "filler_word_removal", "jump_cut"):
            for seg in op.segments or (
                [{"start": op.start, "end": op.end}]
                if op.start is not None and op.end is not None
                else []
            ):
                out.append({"start": float(seg["start"]), "end": float(seg["end"])})
    return out


async def preview_proposal(db: AsyncSession, project: Project, msg: ChatMessage) -> dict[str, Any]:
    proposal = msg.proposal or {}
    if proposal.get("status") in (None, "pending"):
        raise ValidationFailed("Proposal is not ready")
    timeline = await ts.get_timeline(
        db, project, uuid.UUID(proposal["timeline_id"]) if proposal.get("timeline_id") else None
    )
    version = await ts.current_version(db, timeline)
    doc = ts.load_document(version)
    ops = _proposal_ops(msg)
    result = apply_operations(doc, ops)
    return {
        "document": result.document.model_dump(mode="json"),
        "duration_before": doc.duration(),
        "duration_after": result.document.duration(),
        "applied": len(result.applied),
        "rejected": [
            {"operation": op.model_dump(mode="json"), "reason": why} for op, why in result.rejected
        ],
        "removed_ranges": removed_ranges(ops),
    }


async def apply_proposal(
    db: AsyncSession, project: Project, user: User, msg: ChatMessage
) -> tuple[Timeline, Any, list[dict[str, Any]]]:
    proposal = msg.proposal or {}
    if proposal.get("status") in (None, "pending"):
        raise ValidationFailed("Proposal is not ready")
    if proposal.get("status") == "applied":
        raise ValidationFailed("Proposal already applied")
    ops = _proposal_ops(msg)
    timeline = await ts.get_timeline(
        db, project, uuid.UUID(proposal["timeline_id"]) if proposal.get("timeline_id") else None
    )
    label = (proposal.get("summary") or "AI edit")[:200]
    jobs: list[dict[str, Any]] = []
    new_version = None
    if ops:
        _, new_version, _result = await ts.apply_ops_to_timeline(
            db,
            project=project,
            timeline=timeline,
            operations=ops,
            label=label,
            source="ai",
            chat_message_id=msg.id,
        )
    for effect in proposal.get("side_effects", []):
        jobs.append(await _run_side_effect(db, project, user, timeline, effect))
    msg.proposal = {
        **proposal,
        "status": "applied",
        "applied_version_id": str(new_version.id) if new_version else None,
        "jobs": jobs,
    }
    await db.commit()
    await db.refresh(msg)
    return timeline, new_version, jobs


async def _run_side_effect(
    db: AsyncSession, project: Project, user: User, timeline: Timeline, effect: dict[str, Any]
) -> dict[str, Any]:
    kind = effect.get("kind")
    if kind == "shorts":
        from cutpilot.services import creator_service

        job = await creator_service.start_short_generation(
            db,
            project=project,
            user=user,
            count=int(effect.get("count", 3)),
            duration=int(effect.get("duration", 45)),
            platform=effect.get("platform"),
        )
        return {"kind": "shorts", "job_id": str(job.id)}
    if kind == "render":
        from cutpilot.services import render_service

        render, job = await render_service.start_render(
            db,
            project=project,
            user=user,
            timeline_id=timeline.id,
            preset=str(effect.get("preset", "youtube_1080p")),
            settings={},
        )
        return {"kind": "render", "job_id": str(job.id), "render_id": str(render.id)}
    return {"kind": kind, "skipped": True}


async def reject_proposal(db: AsyncSession, msg: ChatMessage) -> ChatMessage:
    proposal = msg.proposal or {}
    msg.proposal = {**proposal, "status": "rejected"}
    await db.commit()
    await db.refresh(msg)
    return msg
