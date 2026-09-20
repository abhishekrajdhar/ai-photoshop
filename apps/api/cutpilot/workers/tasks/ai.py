"""AI worker tasks: chat turns, direct planner runs (creator tasks are added in Phase 7)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cutpilot.ai.chat import run_chat
from cutpilot.ai.context import load_context
from cutpilot.ai.planner import PlanRequest, get_planner
from cutpilot.core.errors import ValidationFailed
from cutpilot.db.models import ChatMessage, ChatSession, MediaAsset, Project, Timeline
from cutpilot.services.events import sync_publisher
from cutpilot.services.job_service import JobContext
from cutpilot.services.timeline_sync import current_version
from cutpilot.workers.base import job_task
from cutpilot.workers.celery_app import celery_app


def _load(
    session: Session, asset_id: str, timeline_id: str
) -> tuple[Project, MediaAsset, Timeline]:
    asset = session.get(MediaAsset, uuid.UUID(asset_id))
    timeline = session.get(Timeline, uuid.UUID(timeline_id))
    if asset is None or timeline is None:
        raise ValidationFailed("Asset or timeline not found")
    project = session.get(Project, asset.project_id)
    assert project is not None
    return project, asset, timeline


def _finish_message(
    session: Session,
    msg: ChatMessage,
    *,
    content: str,
    proposal: dict[str, Any],
    tool_calls: list[Any],
    project_id: uuid.UUID,
) -> None:
    msg.content = content
    msg.proposal = proposal
    msg.tool_calls = tool_calls
    session.commit()
    sync_publisher.publish(
        "chat.message",
        {
            "message_id": str(msg.id),
            "session_id": str(msg.session_id),
            "status": proposal.get("status"),
        },
        project_id=project_id,
    )


def _fail_message(session: Session, msg: ChatMessage, error: str, project_id: uuid.UUID) -> None:
    msg.content = f"Sorry — I couldn't complete that: {error}"
    msg.proposal = {
        "status": "failed",
        "summary": "",
        "operations": [],
        "estimated_duration_delta": None,
        "warnings": [error],
    }
    session.commit()
    sync_publisher.publish(
        "chat.message",
        {"message_id": str(msg.id), "session_id": str(msg.session_id), "status": "failed"},
        project_id=project_id,
    )


@celery_app.task(bind=True, name="cutpilot.workers.tasks.ai.run_chat_task", max_retries=0)
@job_task
def run_chat_task(
    ctx: JobContext, session: Session, *, message_id: str, asset_id: str, timeline_id: str
) -> dict[str, Any]:
    msg = session.get(ChatMessage, uuid.UUID(message_id))
    if msg is None:
        raise ValidationFailed("Message not found")
    project, asset, timeline = _load(session, asset_id, timeline_id)
    try:
        version = current_version(session, timeline)
        assert version is not None
        pctx = load_context(session, project, asset, version)
        chat_session = session.get(ChatSession, msg.session_id)
        history = [
            {"role": m.role, "content": m.content}
            for m in session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == msg.session_id, ChatMessage.id != msg.id)
                .order_by(ChatMessage.created_at)
            )
            .scalars()
            .all()
        ]
        user_message = history.pop()["content"] if history and history[-1]["role"] == "user" else ""
        ctx.progress(0.1, "Thinking")
        outcome = run_chat(
            session,
            pctx,
            history,
            user_message,
            user_id=ctx.job.user_id,
            on_progress=lambda m: ctx.progress(0.5, m),
        )
        proposal = {
            "status": "proposed" if (outcome.operations or outcome.side_effects) else "none",
            "summary": outcome.summary,
            "operations": [op.model_dump(mode="json") for op in outcome.operations],
            "estimated_duration_delta": outcome.estimated_duration_delta,
            "duration_after": outcome.duration_after,
            "warnings": outcome.warnings,
            "rejected": outcome.rejected,
            "side_effects": outcome.side_effects,
            "timeline_id": str(timeline.id),
            "base_version_id": str(version.id),
        }
        _finish_message(
            session,
            msg,
            content=outcome.content,
            proposal=proposal,
            tool_calls=outcome.tool_calls,
            project_id=project.id,
        )
        if chat_session and chat_session.title in ("Editing chat", "New chat") and user_message:
            chat_session.title = user_message[:60]
            session.commit()
        return {"message_id": str(msg.id), "operations": len(outcome.operations)}
    except Exception as exc:
        session.rollback()
        _fail_message(session, msg, str(exc), project.id)
        raise


@celery_app.task(bind=True, name="cutpilot.workers.tasks.ai.plan_edit_task", max_retries=0)
@job_task
def plan_edit_task(
    ctx: JobContext,
    session: Session,
    *,
    message_id: str,
    asset_id: str,
    timeline_id: str,
    instruction: str,
    target_platform: str | None = None,
    target_duration: float | None = None,
) -> dict[str, Any]:
    msg = session.get(ChatMessage, uuid.UUID(message_id))
    if msg is None:
        raise ValidationFailed("Message not found")
    project, asset, timeline = _load(session, asset_id, timeline_id)
    try:
        version = current_version(session, timeline)
        assert version is not None
        pctx = load_context(session, project, asset, version)
        ctx.progress(0.1, "Planning edit")
        planner = get_planner(session, project_id=project.id, user_id=ctx.job.user_id)
        result = planner.plan(
            pctx,
            PlanRequest(
                instruction=instruction,
                target_platform=target_platform,
                target_duration=target_duration,
            ),
        )
        proposal = {
            "status": "proposed" if result.operations else "none",
            "summary": result.edl.summary,
            "operations": [op.model_dump(mode="json") for op in result.operations],
            "estimated_duration_delta": result.edl.estimated_duration_delta,
            "duration_after": result.duration_after,
            "warnings": result.edl.warnings + result.notes,
            "rejected": result.rejected,
            "side_effects": [],
            "timeline_id": str(timeline.id),
            "base_version_id": str(version.id),
            "provider": result.provider,
            "model": result.model,
        }
        content = result.edl.summary or "Here is the proposed edit."
        _finish_message(
            session, msg, content=content, proposal=proposal, tool_calls=[], project_id=project.id
        )
        return {"message_id": str(msg.id), "operations": len(result.operations)}
    except Exception as exc:
        session.rollback()
        _fail_message(session, msg, str(exc), project.id)
        raise
