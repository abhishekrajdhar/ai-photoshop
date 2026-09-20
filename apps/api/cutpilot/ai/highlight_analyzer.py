"""Highlight detection with explained scoring factors (LLM-assisted, validated)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from cutpilot.ai.context import ProjectContext, analysis_summary, select_transcript
from cutpilot.ai.prompts import render_prompt
from cutpilot.ai.providers.base import Message
from cutpilot.ai.router import AIRouter

FACTORS = (
    "informative",
    "surprising",
    "funny",
    "emotional",
    "hook_strength",
    "clarity",
    "self_contained",
)


class HighlightItem(BaseModel):
    start: float
    end: float
    title: str = ""
    caption_suggestion: str = ""
    reason: str = ""
    category: str = "informative"
    factors: dict[str, float] = Field(default_factory=dict)
    hook_line: str = ""


class HighlightList(BaseModel):
    highlights: list[HighlightItem] = Field(default_factory=list)


def composite_score(factors: dict[str, float]) -> float:
    """Transparent weighted sum — the factors themselves are stored and shown to the user."""
    weights = {
        "informative": 0.2,
        "surprising": 0.15,
        "funny": 0.1,
        "emotional": 0.1,
        "hook_strength": 0.2,
        "clarity": 0.15,
        "self_contained": 0.1,
    }
    total = sum(weights[k] * float(min(1.0, max(0.0, factors.get(k, 0.0)))) for k in weights)
    return round(total, 4)


def detect_highlights(
    router: AIRouter,
    ctx: ProjectContext,
    *,
    count: int = 5,
    min_len: float = 20.0,
    max_len: float = 60.0,
    platform: str | None = None,
) -> list[dict[str, Any]]:
    if not ctx.transcript_segments:
        raise ValueError("Highlights need a transcript")
    transcript, _note = select_transcript(
        ctx, "best moments highlights hooks strongest sections", budget_words=9000
    )
    prompt = render_prompt(
        "highlights",
        context=f"'{ctx.project.name}'. {ctx.project.description or ''}",
        platform=platform or (ctx.project.settings or {}).get("target_platform", "youtube_shorts"),
        min_len=f"{min_len:.0f}",
        max_len=f"{max_len:.0f}",
        count=count,
        transcript=transcript,
        analysis=analysis_summary(ctx)[:12000],
    )
    parsed, _ = router.complete_structured(
        HighlightList,
        operation="highlights",
        messages=[Message(role="user", content=prompt)],
        max_tokens=8000,
    )
    out: list[dict[str, Any]] = []
    for h in parsed.highlights:
        start, end = max(0.0, h.start), min(ctx.duration or h.end, h.end)
        if end - start < min(8.0, min_len / 2):
            continue
        if end - start > max_len * 1.5:
            end = start + max_len
        factors = {k: round(float(min(1.0, max(0.0, h.factors.get(k, 0.0)))), 3) for k in FACTORS}
        out.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "title": h.title[:200] or "Highlight",
                "caption_suggestion": h.caption_suggestion[:400],
                "reason": h.reason[:1000],
                "category": h.category[:64],
                "factors": factors,
                "score": composite_score(factors),
                "hook_line": h.hook_line[:300],
            }
        )
    # No overlaps: keep the higher-scored of overlapping pairs
    out.sort(key=lambda x: -x["score"])
    kept: list[dict[str, Any]] = []
    for h in out:
        if all(h["end"] <= k["start"] or h["start"] >= k["end"] for k in kept):
            kept.append(h)
    return sorted(kept[:count], key=lambda x: x["start"])
