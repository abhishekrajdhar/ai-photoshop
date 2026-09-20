"""Builds the compact, token-budgeted project context handed to the planner and the chat editor."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cutpilot.ai.expansion import current_transcript, latest_result
from cutpilot.db.models import (
    MediaAsset,
    MediaMetadata,
    Project,
    Speaker,
    TimelineVersion,
    TranscriptSegment,
)
from cutpilot.timeline.model import TimelineDocument

WORD_BUDGET_FULL = 6000  # transcripts up to this many words are sent verbatim


@dataclass
class ProjectContext:
    project: Project
    asset: MediaAsset
    duration: float
    document: TimelineDocument
    transcript_segments: list[dict[str, Any]] = field(default_factory=list)
    speakers: dict[str, str] = field(default_factory=dict)
    silence: dict[str, Any] | None = None
    filler: dict[str, Any] | None = None
    content: dict[str, Any] | None = None
    vision: dict[str, Any] | None = None
    scenes: list[dict[str, Any]] = field(default_factory=list)
    audio_stats: dict[str, Any] | None = None
    highlights: list[dict[str, Any]] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return sum(len(str(s["text"]).split()) for s in self.transcript_segments)

    def has_transcript(self) -> bool:
        return bool(self.transcript_segments)


def load_context(
    session: Session, project: Project, asset: MediaAsset, version: TimelineVersion
) -> ProjectContext:
    meta = session.execute(
        select(MediaMetadata).where(MediaMetadata.asset_id == asset.id)
    ).scalar_one_or_none()
    duration = float(meta.duration or 0.0) if meta else 0.0
    ctx = ProjectContext(
        project=project,
        asset=asset,
        duration=duration,
        document=TimelineDocument.model_validate(version.document),
    )
    transcript = current_transcript(session, project.id, asset.id)
    if transcript:
        speakers = {
            str(s.id): s.display_name
            for s in session.execute(select(Speaker).where(Speaker.transcript_id == transcript.id))
            .scalars()
            .all()
        }
        ctx.speakers = speakers
        for seg in (
            session.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id == transcript.id)
                .order_by(TranscriptSegment.index)
            )
            .scalars()
            .all()
        ):
            ctx.transcript_segments.append(
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                    "speaker": speakers.get(str(seg.speaker_id)) if seg.speaker_id else None,
                }
            )
    for kind in ("silence", "filler", "content", "vision", "audio_stats"):
        res = latest_result(session, asset.id, kind)
        if res:
            setattr(ctx, kind, res.data)
    scenes_res = latest_result(session, asset.id, "scenes")
    if scenes_res:
        ctx.scenes = scenes_res.data.get("scenes", [])
    from cutpilot.db.models import Highlight

    ctx.highlights = [
        {
            "start": h.start,
            "end": h.end,
            "title": h.title,
            "score": h.score,
            "category": h.category,
            "reason": h.reason,
        }
        for h in session.execute(
            select(Highlight)
            .where(Highlight.project_id == project.id)
            .order_by(Highlight.score.desc())
            .limit(12)
        )
        .scalars()
        .all()
    ]
    return ctx


# ── rendering helpers ────────────────────────────────────────────────────────


def format_transcript(segments: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{s['start']:.1f}-{s['end']:.1f}] {(s.get('speaker') + ': ') if s.get('speaker') else ''}{s['text']}"
        for s in segments
    )


_STOP = set(
    "the a an and or of to in on for with this that these those is are was were be been it its i you we they he she them our your my me us do does did have has had not no yes so um uh like just very really make edit video into from about what which who how when where why can could should would want need please turn create remove add cut keep get".split()
)


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", text.lower()) if w not in _STOP}


def select_transcript(
    ctx: ProjectContext, instruction: str, *, budget_words: int = WORD_BUDGET_FULL
) -> tuple[str, str]:
    """Return (transcript_text, note). Long transcripts are reduced to section summaries plus the
    segments most relevant to the instruction (keyword retrieval), keeping token usage bounded."""
    if ctx.word_count <= budget_words:
        return format_transcript(ctx.transcript_segments), "full transcript"
    sections = (ctx.content or {}).get("sections", [])
    keys = _keywords(instruction)
    scored: list[tuple[int, dict[str, Any]]] = []
    for seg in ctx.transcript_segments:
        score = len(keys & _keywords(str(seg["text"])))
        scored.append((score, seg))
    relevant = sorted([s for s in scored if s[0] > 0], key=lambda x: -x[0])[:200]
    chosen = sorted((s for _, s in relevant), key=lambda s: s["start"])
    # Always include the opening and closing minute for structure.
    head = [s for s in ctx.transcript_segments if s["end"] <= 60]
    tail = [s for s in ctx.transcript_segments if s["start"] >= ctx.duration - 60]
    merged = {id(s): s for s in head + chosen + tail}
    parts = ["# Section summaries (timestamps in seconds)"]
    for sec in sections:
        parts.append(
            f"[{sec.get('section_start', 0):.0f}-{sec.get('section_end', 0):.0f}] {sec.get('summary', '')} topics={sec.get('topics', [])}"
        )
    parts.append("\n# Selected transcript segments")
    parts.append(format_transcript(sorted(merged.values(), key=lambda s: s["start"])))
    return (
        "\n".join(parts),
        f"reduced transcript ({ctx.word_count} words → {len(merged)} segments + {len(sections)} section summaries)",
    )


def timeline_summary(doc: TimelineDocument, asset_names: dict[str, str] | None = None) -> str:
    lines = [
        f"Sequence {doc.settings.width}x{doc.settings.height} @ {doc.settings.fps} fps, aspect {doc.settings.aspect_ratio}, duration {doc.duration():.1f}s"
    ]
    for t in doc.tracks:
        if not t.clips:
            continue
        lines.append(
            f"Track {t.id} ({t.kind}, {t.name}){' muted' if t.muted else ''}{' locked' if t.locked else ''}:"
        )
        for c in t.sorted_clips()[:60]:
            name = (asset_names or {}).get(c.asset_id or "", c.name)
            extra = f" text='{(c.text or '')[:40]}'" if c.text else ""
            fx = f" effects={[e.type for e in c.effects]}" if c.effects else ""
            lines.append(
                f"  clip {c.id} kind={c.kind} asset={c.asset_id} ({name}) timeline {c.timeline_start:.2f}-{c.timeline_end:.2f} source {c.source_in:.2f}-{c.source_out:.2f} speed={c.speed}{extra}{fx}"
            )
        if len(t.clips) > 60:
            lines.append(f"  … {len(t.clips) - 60} more clips")
    if doc.markers:
        lines.append(
            "Markers: " + ", ".join(f"{m.time:.1f}s {m.kind} '{m.label}'" for m in doc.markers[:20])
        )
    return "\n".join(lines)


def analysis_summary(ctx: ProjectContext) -> str:
    parts: list[str] = []
    if ctx.silence:
        parts.append(
            f"Silence analysis: {ctx.silence.get('count', 0)} pauses, {ctx.silence.get('removable_seconds', 0)}s removable via silence_removal auto. Longest pauses: {json.dumps(sorted(ctx.silence.get('suggested_cuts', []), key=lambda c: -c['duration'])[:8])}"
        )
    if ctx.filler:
        parts.append(
            f"Filler words: {ctx.filler.get('count', 0)} detected ({ctx.filler.get('removable_seconds', 0)}s) via filler_word_removal auto. Examples: {[h['text'] for h in ctx.filler.get('hits', [])[:12]]}"
        )
    if ctx.audio_stats:
        parts.append(f"Audio stats: {json.dumps(ctx.audio_stats)}")
    if ctx.content:
        summary = ctx.content.get("summary", {})
        agg = ctx.content.get("aggregate", {})
        parts.append(
            "Content summary: "
            + json.dumps(
                {
                    k: summary.get(k)
                    for k in ("summary", "topics", "chapters", "best_hooks", "pacing_notes", "tone")
                }
            )
        )
        for key in (
            "key_statements",
            "weak_segments",
            "repeated_statements",
            "tangents",
            "removable_candidates",
            "short_form_moments",
            "broll_opportunities",
            "strong_segments",
        ):
            items = agg.get(key, [])
            if items:
                parts.append(f"{key} ({len(items)}): {json.dumps(items[:25])}")
    if ctx.scenes:
        parts.append(
            f"Scenes ({len(ctx.scenes)}): {json.dumps([{'start': s['start'], 'end': s['end']} for s in ctx.scenes[:40]])}"
        )
    if ctx.vision:
        parts.append(
            "Vision: "
            + json.dumps(
                {
                    "scenes": ctx.vision.get("scenes", [])[:10],
                    "editing_opportunities": ctx.vision.get("editing_opportunities", [])[:15],
                    "issues": [
                        {"t": f["t"], "issues": f["issues"]}
                        for f in ctx.vision.get("frames", [])
                        if f.get("issues")
                    ][:10],
                }
            )
        )
    if ctx.highlights:
        parts.append("Highlights: " + json.dumps(ctx.highlights))
    return "\n".join(parts) if parts else "No analysis available yet."


def asset_names(session: Session, project_id: uuid.UUID) -> dict[str, str]:
    return {
        str(a.id): a.filename
        for a in session.execute(select(MediaAsset).where(MediaAsset.project_id == project_id))
        .scalars()
        .all()
    }
