"""Conversational editor: LLM + internal tools → assistant reply + staged proposal."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from cutpilot.ai.context import ProjectContext
from cutpilot.ai.expansion import estimate_duration_delta, expand_operations
from cutpilot.ai.prompts import render_prompt
from cutpilot.ai.providers.base import Message
from cutpilot.ai.router import AIRouter
from cutpilot.ai.tools import TOOL_SPECS, ToolSession, run_tool
from cutpilot.core.constants import PRODUCT_NAME
from cutpilot.core.logging import get_logger
from cutpilot.timeline.engine import apply_operations
from cutpilot.timeline.operations import EditOperation

log = get_logger(__name__)
MAX_TOOL_ROUNDS = 8


@dataclass
class ChatOutcome:
    content: str
    operations: list[EditOperation]
    summary: str
    estimated_duration_delta: float | None
    warnings: list[str]
    tool_calls: list[dict[str, Any]]
    side_effects: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    duration_after: float


def run_chat(
    session: Session,
    ctx: ProjectContext,
    history: list[dict[str, str]],
    user_message: str,
    *,
    user_id: uuid.UUID | None,
    on_progress=None,
) -> ChatOutcome:  # type: ignore[no-untyped-def]
    router = AIRouter(session, project_id=ctx.project.id, user_id=user_id)
    doc = ctx.document
    system = render_prompt(
        "chat_system",
        product=PRODUCT_NAME,
        project_summary=f"'{ctx.project.name}'. {ctx.project.description or ''} Platform: {(ctx.project.settings or {}).get('target_platform', 'generic')}.",
        asset_id=str(ctx.asset.id),
        duration=f"{ctx.duration:.1f}",
        timeline_brief=f"{doc.settings.width}x{doc.settings.height} {doc.settings.aspect_ratio}, {doc.duration():.1f}s, {sum(len(t.clips) for t in doc.tracks)} clips",
        analysis_available=", ".join(
            k
            for k, v in (
                ("silence", ctx.silence),
                ("filler", ctx.filler),
                ("content", ctx.content),
                ("vision", ctx.vision),
                ("scenes", ctx.scenes),
                ("highlights", ctx.highlights),
            )
            if v
        )
        or "none",
        transcript_available=f"{ctx.word_count} words" if ctx.has_transcript() else "none",
    )
    messages: list[Message] = [
        Message(role=m["role"], content=m["content"])
        for m in history[-12:]
        if m["role"] in ("user", "assistant") and m["content"]
    ]  # type: ignore[arg-type]
    messages.append(Message(role="user", content=user_message))
    ts = ToolSession(session=session, ctx=ctx, user_id=user_id)
    tool_log: list[dict[str, Any]] = []
    final_text = ""
    for round_no in range(MAX_TOOL_ROUNDS + 1):
        res = router.complete(
            operation="chat",
            messages=messages,
            system=system,
            tools=TOOL_SPECS,
            max_tokens=2500,
            temperature=0.3,
            meta={"round": round_no},
        )
        if not res.tool_calls:
            final_text = res.text or ""
            break
        messages.append(
            Message(role="assistant", content=res.text or "", tool_calls=res.tool_calls)
        )
        for tc in res.tool_calls:
            if on_progress:
                on_progress(f"Running {tc.name}")
            try:
                output = run_tool(ts, tc.name, tc.arguments)
            except Exception as exc:
                log.warning("chat_tool_failed", tool=tc.name, error=str(exc))
                output = f"Tool error: {exc}"
            tool_log.append({"name": tc.name, "arguments": tc.arguments, "result": output[:600]})
            messages.append(Message(role="tool", content=output, tool_call_id=tc.id))
    else:
        final_text = "I staged the changes described above."
    if not final_text and ts.staged:
        final_text = ts.plan_summary or "I prepared a proposal for you to review."

    # Expand macros + dry-run so the proposal only contains applicable operations.
    expanded, notes = expand_operations(
        session,
        project_id=ctx.project.id,
        asset_id=ctx.asset.id,
        operations=ts.staged,
        caption_style=doc.settings.caption_style.model_dump(),
    )
    dry = apply_operations(doc, expanded)
    rejected = [
        {"operation": op.model_dump(mode="json"), "reason": why} for op, why in dry.rejected
    ]
    delta = (
        ts.plan_delta
        if ts.plan_delta is not None
        else (estimate_duration_delta(dry.applied) if dry.applied else None)
    )
    return ChatOutcome(
        content=final_text,
        operations=dry.applied,
        summary=ts.plan_summary or _auto_summary(dry.applied),
        estimated_duration_delta=delta,
        warnings=[*ts.warnings, *notes],
        tool_calls=tool_log,
        side_effects=ts.side_effects,
        rejected=rejected,
        duration_after=dry.document.duration(),
    )


def _auto_summary(ops: list[EditOperation]) -> str:
    if not ops:
        return ""
    counts: dict[str, int] = {}
    for op in ops:
        counts[op.type] = counts.get(op.type, 0) + 1
    return ", ".join(f"{n} x {t.replace('_', ' ')}" for t, n in counts.items())
