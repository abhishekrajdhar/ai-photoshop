"""AI editing planner: instruction + project context → validated EditDecisionList.

`EditingPlannerProvider` is the abstraction; `OpenAIEditingPlanner` / `AnthropicEditingPlanner` pin a
provider, and `get_planner()` picks the configured one with automatic fallback. All variants share the
same prompt, schema validation and repair loop (via AIRouter.complete_structured).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from cutpilot.ai.context import (
    ProjectContext,
    analysis_summary,
    asset_names,
    select_transcript,
    timeline_summary,
)
from cutpilot.ai.expansion import estimate_duration_delta, expand_operations
from cutpilot.ai.prompts import render_prompt
from cutpilot.ai.providers.base import Message
from cutpilot.ai.router import AIRouter, available_providers
from cutpilot.core.config import AIProviderName, get_settings
from cutpilot.core.constants import PRODUCT_NAME
from cutpilot.core.errors import AIConfigurationError
from cutpilot.core.logging import get_logger
from cutpilot.timeline.engine import apply_operations
from cutpilot.timeline.operations import EditDecisionList, EditOperation

log = get_logger(__name__)


@dataclass
class PlanRequest:
    instruction: str
    target_platform: str | None = None
    target_duration: float | None = None  # seconds
    extra_context: str = ""


@dataclass
class PlanResult:
    edl: EditDecisionList
    operations: list[EditOperation]  # expanded + validated against the current timeline
    rejected: list[dict[str, Any]]
    notes: list[str]
    provider: str
    model: str
    duration_before: float
    duration_after: float


class EditingPlannerProvider:
    provider: AIProviderName | None = None

    def __init__(
        self, session: Session, *, project_id: uuid.UUID, user_id: uuid.UUID | None = None
    ):
        self.session = session
        self.router = AIRouter(session, project_id=project_id, user_id=user_id)

    def plan(self, ctx: ProjectContext, request: PlanRequest) -> PlanResult:
        settings = ctx.project.settings or {}
        platform = request.target_platform or settings.get("target_platform", "generic")
        transcript_text, note = select_transcript(ctx, request.instruction)
        names = asset_names(self.session, ctx.project.id)
        prompt = render_prompt(
            "editing_planner",
            product=PRODUCT_NAME,
            project_summary=f"'{ctx.project.name}'. {ctx.project.description or ''}".strip(),
            platform=platform,
            target_duration=f"{request.target_duration:.0f}s"
            if request.target_duration
            else "not specified",
            asset_id=str(ctx.asset.id),
            duration=f"{ctx.duration:.1f}",
            timeline=timeline_summary(ctx.document, names),
            analysis=analysis_summary(ctx),
            transcript_note=note,
            transcript=transcript_text
            or "(no transcript — only silence/scene based edits are possible)",
            instruction=request.instruction
            + (f"\n\nAdditional context: {request.extra_context}" if request.extra_context else ""),
        )
        edl, response = self._complete(prompt)
        return self.finalize(ctx, edl, provider=response.provider, model=response.model)

    def _complete(self, prompt: str):  # type: ignore[no-untyped-def]
        # Pin a provider order when this planner is provider-specific.
        if self.provider and self.provider not in available_providers():
            raise AIConfigurationError(f"{self.provider} is not configured")
        return self.router.complete_structured(
            EditDecisionList,
            operation="planner",
            messages=[Message(role="user", content=prompt)],
            max_tokens=16000,
            temperature=0.2,
            meta={"planner": self.provider or "auto"},
        )

    def finalize(
        self, ctx: ProjectContext, edl: EditDecisionList, *, provider: str, model: str
    ) -> PlanResult:
        """Expand macros, tag as AI, dry-run against the timeline, drop anything the engine rejects."""
        for op in edl.operations:
            op.source = "ai"
            if op.asset_id is None and op.time_ref == "source" and op.source_clip_id is None:
                op.asset_id = str(ctx.asset.id)
        expanded, notes = expand_operations(
            self.session,
            project_id=ctx.project.id,
            asset_id=ctx.asset.id,
            operations=edl.operations,
            caption_style=ctx.document.settings.caption_style.model_dump(),
        )
        dry = apply_operations(ctx.document, expanded)
        rejected = [
            {"operation": op.model_dump(mode="json"), "reason": why} for op, why in dry.rejected
        ]
        if rejected:
            log.warning("planner_rejected_ops", count=len(rejected))
        if edl.estimated_duration_delta is None:
            edl.estimated_duration_delta = estimate_duration_delta(dry.applied)
        return PlanResult(
            edl=edl,
            operations=dry.applied,
            rejected=rejected,
            notes=notes,
            provider=provider,
            model=model,
            duration_before=ctx.document.duration(),
            duration_after=dry.document.duration(),
        )


class OpenAIEditingPlanner(EditingPlannerProvider):
    provider = "openai"


class AnthropicEditingPlanner(EditingPlannerProvider):
    provider = "anthropic"


class AutoEditingPlanner(EditingPlannerProvider):
    """Preferred provider with fallback (router decides)."""

    provider = None


def get_planner(
    session: Session, *, project_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> EditingPlannerProvider:
    settings = get_settings()
    avail = available_providers()
    if not avail:
        raise AIConfigurationError(
            "No AI provider configured. Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY."
        )
    if settings.ai_provider in avail and settings.ai_fallback_provider in avail:
        return AutoEditingPlanner(session, project_id=project_id, user_id=user_id)
    cls = OpenAIEditingPlanner if avail[0] == "openai" else AnthropicEditingPlanner
    return cls(session, project_id=project_id, user_id=user_id)
