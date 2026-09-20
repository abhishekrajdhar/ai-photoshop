"""Hierarchical transcript analysis: sections → structured metadata → project summary."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from cutpilot.ai.prompts import render_prompt
from cutpilot.ai.providers.base import Message
from cutpilot.ai.router import AIRouter


class TimedText(BaseModel):
    start: float
    end: float
    text: str = ""
    importance: float | None = None
    kind: str | None = None
    reason: str | None = None
    repeats: str | None = None
    confidence: float | None = None
    score: float | None = None
    query: str | None = None


class SectionAnalysis(BaseModel):
    summary: str = ""
    topics: list[str] = Field(default_factory=list)
    key_statements: list[TimedText] = Field(default_factory=list)
    hooks: list[TimedText] = Field(default_factory=list)
    weak_segments: list[TimedText] = Field(default_factory=list)
    repeated_statements: list[TimedText] = Field(default_factory=list)
    tangents: list[TimedText] = Field(default_factory=list)
    strong_segments: list[TimedText] = Field(default_factory=list)
    removable_candidates: list[TimedText] = Field(default_factory=list)
    short_form_moments: list[TimedText] = Field(default_factory=list)
    broll_opportunities: list[TimedText] = Field(default_factory=list)
    # filled in by us
    section_start: float = 0.0
    section_end: float = 0.0


class Chapter(BaseModel):
    start: float
    end: float
    title: str


class ProjectSummary(BaseModel):
    title_suggestions: list[str] = Field(default_factory=list)
    summary: str = ""
    topics: list[str] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    best_hooks: list[TimedText] = Field(default_factory=list)
    structure_notes: str = ""
    pacing_notes: str = ""
    audience: str = ""
    tone: str = ""


def format_segments(
    segments: list[dict[str, Any]], *, speakers: dict[str, str] | None = None
) -> str:
    lines = []
    for s in segments:
        spk = ""
        if speakers and s.get("speaker_id") and s["speaker_id"] in speakers:
            spk = f"{speakers[s['speaker_id']]}: "
        lines.append(f"[{s['start']:.1f}-{s['end']:.1f}] {spk}{s['text']}")
    return "\n".join(lines)


def chunk_segments(
    segments: list[dict[str, Any]], *, max_words: int = 700, max_seconds: float = 360.0
) -> list[list[dict[str, Any]]]:
    """Group transcript segments into sections small enough for one focused LLM call."""
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    words = 0
    for seg in segments:
        seg_words = len(str(seg["text"]).split())
        span = (seg["end"] - current[0]["start"]) if current else 0
        if current and (words + seg_words > max_words or span > max_seconds):
            chunks.append(current)
            current, words = [], 0
        current.append(seg)
        words += seg_words
    if current:
        chunks.append(current)
    return chunks


def analyze_transcript(
    router: AIRouter,
    segments: list[dict[str, Any]],
    *,
    context: str,
    duration: float,
    speakers: dict[str, str] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    chunks = chunk_segments(segments)
    sections: list[SectionAnalysis] = []
    for i, chunk in enumerate(chunks):
        prompt = render_prompt(
            "transcript_section",
            context=context,
            section_start=f"{chunk[0]['start']:.1f}",
            section_end=f"{chunk[-1]['end']:.1f}",
            transcript=format_segments(chunk, speakers=speakers),
        )
        section, _ = router.complete_structured(
            SectionAnalysis,
            operation="transcript_analysis",
            messages=[Message(role="user", content=prompt)],
            max_tokens=3000,
            meta={"section": i},
        )
        section.section_start, section.section_end = chunk[0]["start"], chunk[-1]["end"]
        _clamp_times(section, chunk[0]["start"], chunk[-1]["end"])
        sections.append(section)
        if on_progress:
            on_progress(0.1 + 0.7 * (i + 1) / len(chunks))
    compact = [s.model_dump(exclude_none=True, exclude={"broll_opportunities"}) for s in sections]
    summary_prompt = render_prompt(
        "transcript_summary",
        context=context,
        duration=f"{duration:.1f}",
        sections=json.dumps(compact)[:60000],
    )
    summary, _ = router.complete_structured(
        ProjectSummary,
        operation="transcript_summary",
        messages=[Message(role="user", content=summary_prompt)],
        max_tokens=2500,
    )
    summary.chapters = _normalize_chapters(summary.chapters, duration)
    if on_progress:
        on_progress(0.95)
    return {
        "summary": summary.model_dump(),
        "sections": [s.model_dump() for s in sections],
        "aggregate": aggregate_sections(sections),
    }


def _clamp_times(section: SectionAnalysis, lo: float, hi: float) -> None:
    for name in (
        "key_statements",
        "hooks",
        "weak_segments",
        "repeated_statements",
        "tangents",
        "strong_segments",
        "removable_candidates",
        "short_form_moments",
        "broll_opportunities",
    ):
        items: list[TimedText] = getattr(section, name)
        kept = []
        for it in items:
            it.start = max(lo, min(hi, it.start))
            it.end = max(lo, min(hi, it.end))
            if it.end > it.start:
                kept.append(it)
        setattr(section, name, kept)


def _normalize_chapters(chapters: list[Chapter], duration: float) -> list[Chapter]:
    if not chapters or duration <= 0:
        return chapters
    chapters = sorted(chapters, key=lambda c: c.start)
    out: list[Chapter] = []
    for i, c in enumerate(chapters):
        start = 0.0 if i == 0 else max(c.start, out[-1].end)
        end = duration if i == len(chapters) - 1 else min(max(c.end, start + 1), duration)
        if end > start:
            out.append(Chapter(start=round(start, 2), end=round(end, 2), title=c.title[:80]))
    # make contiguous
    for i in range(len(out) - 1):
        out[i].end = out[i + 1].start
    return out


def aggregate_sections(sections: list[SectionAnalysis]) -> dict[str, list[dict[str, Any]]]:
    agg: dict[str, list[dict[str, Any]]] = {}
    for name in (
        "key_statements",
        "hooks",
        "weak_segments",
        "repeated_statements",
        "tangents",
        "strong_segments",
        "removable_candidates",
        "short_form_moments",
        "broll_opportunities",
    ):
        items: list[dict[str, Any]] = []
        for s in sections:
            items.extend(it.model_dump(exclude_none=True) for it in getattr(s, name))
        agg[name] = sorted(items, key=lambda x: x["start"])
    return agg
