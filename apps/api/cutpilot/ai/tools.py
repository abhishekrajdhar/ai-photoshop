"""Internal editing tools exposed to the chat LLM. Tools read project data or *stage* operations.

Staged operations are collected into a proposal; nothing is applied until the user approves.
The LLM never executes shell commands or touches media.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cutpilot.ai.context import (
    ProjectContext,
    analysis_summary,
    format_transcript,
    timeline_summary,
)
from cutpilot.ai.planner import PlanRequest, get_planner
from cutpilot.ai.providers.base import ToolSpec
from cutpilot.timeline.operations import EditOperation


@dataclass
class ToolSession:
    session: Session
    ctx: ProjectContext
    user_id: uuid.UUID | None
    staged: list[EditOperation] = field(default_factory=list)
    plan_summary: str | None = None
    plan_delta: float | None = None
    warnings: list[str] = field(default_factory=list)
    side_effects: list[dict[str, Any]] = field(
        default_factory=list
    )  # e.g. jobs requested (shorts, render)


def _num(v: Any, default: float | None = None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        "get_transcript",
        "Read the transcript with timestamps (source seconds). Optionally limit to a time range.",
        {
            "type": "object",
            "properties": {"start": {"type": "number"}, "end": {"type": "number"}},
            "required": [],
        },
    ),
    ToolSpec(
        "get_timeline",
        "Describe the current timeline: tracks, clips, source ranges, effects.",
        {"type": "object", "properties": {}},
    ),
    ToolSpec(
        "get_audio_analysis",
        "Silence, filler-word and loudness analysis of the primary asset.",
        {"type": "object", "properties": {}},
    ),
    ToolSpec(
        "get_scene_metadata",
        "Scene boundaries and visual analysis notes.",
        {"type": "object", "properties": {}},
    ),
    ToolSpec(
        "get_content_analysis",
        "LLM content analysis: summary, chapters, key statements, weak/removable sections, hooks, short-form moments.",
        {"type": "object", "properties": {}},
    ),
    ToolSpec(
        "plan_edit",
        "Run the editing planner on a precise instruction to produce a full operation list (use for multi-step or creative requests).",
        {
            "type": "object",
            "properties": {
                "instruction": {"type": "string"},
                "target_duration_seconds": {"type": "number"},
                "target_platform": {"type": "string"},
            },
            "required": ["instruction"],
        },
    ),
    ToolSpec(
        "remove_segment",
        "Stage removal of source time ranges of the primary asset.",
        {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"start": {"type": "number"}, "end": {"type": "number"}},
                        "required": ["start", "end"],
                    },
                },
                "reason": {"type": "string"},
            },
            "required": ["segments"],
        },
    ),
    ToolSpec(
        "remove_silences",
        "Stage removal of all detected pauses (optionally only pauses longer than min_duration seconds).",
        {"type": "object", "properties": {"min_duration": {"type": "number"}}, "required": []},
    ),
    ToolSpec(
        "remove_filler_words",
        "Stage removal of all detected filler words.",
        {"type": "object", "properties": {}},
    ),
    ToolSpec(
        "create_cut",
        "Stage a split of the timeline at a source timestamp (a cut point).",
        {
            "type": "object",
            "properties": {"timestamp": {"type": "number"}},
            "required": ["timestamp"],
        },
    ),
    ToolSpec(
        "add_caption",
        "Stage captions. With auto=true captions are generated from transcript word timestamps; otherwise supply start/end/text.",
        {
            "type": "object",
            "properties": {
                "auto": {"type": "boolean"},
                "preset": {"type": "string", "enum": ["clean", "bold", "karaoke", "minimal"]},
                "start": {"type": "number"},
                "end": {"type": "number"},
                "text": {"type": "string"},
            },
            "required": [],
        },
    ),
    ToolSpec(
        "add_zoom",
        "Stage a subtle emphasis zoom at a source timestamp.",
        {
            "type": "object",
            "properties": {
                "timestamp": {"type": "number"},
                "duration": {"type": "number"},
                "scale": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["timestamp"],
        },
    ),
    ToolSpec(
        "add_broll",
        "Stage a B-roll suggestion (search query) at a source timestamp.",
        {
            "type": "object",
            "properties": {
                "timestamp": {"type": "number"},
                "duration": {"type": "number"},
                "query": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["timestamp", "query"],
        },
    ),
    ToolSpec(
        "reframe_clip",
        "Stage a reframe of the sequence to a new aspect ratio with subject tracking.",
        {
            "type": "object",
            "properties": {
                "aspect_ratio": {"type": "string", "enum": ["9:16", "1:1", "4:5", "16:9"]},
                "mode": {"type": "string", "enum": ["track", "center"]},
            },
            "required": ["aspect_ratio"],
        },
    ),
    ToolSpec(
        "adjust_audio",
        "Stage audio processing: normalize loudness, reduce noise, enhance voice, or set gain in dB.",
        {
            "type": "object",
            "properties": {
                "normalize": {"type": "boolean"},
                "noise_reduction": {"type": "boolean"},
                "voice_enhancement": {"type": "boolean"},
                "gain_db": {"type": "number"},
            },
            "required": [],
        },
    ),
    ToolSpec(
        "create_short",
        "Start generating short-form clips (9:16, captions, jump cuts) from the strongest moments.",
        {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "duration_seconds": {"type": "integer", "enum": [15, 30, 45, 60, 90]},
                "platform": {"type": "string"},
            },
            "required": [],
        },
    ),
    ToolSpec(
        "render_video",
        "Start rendering the current timeline with an export preset.",
        {"type": "object", "properties": {"preset": {"type": "string"}}, "required": []},
    ),
]


def run_tool(ts: ToolSession, name: str, args: dict[str, Any]) -> str:
    ctx = ts.ctx
    asset_id = str(ctx.asset.id)
    if name == "get_transcript":
        if not ctx.transcript_segments:
            return "No transcript yet. Ask the user to run Transcribe."
        start, end = (
            _num(args.get("start"), 0.0) or 0.0,
            _num(args.get("end"), ctx.duration) or ctx.duration,
        )
        segs = [s for s in ctx.transcript_segments if s["end"] >= start and s["start"] <= end]
        text = format_transcript(segs)
        return text[:20000] + ("\n…(truncated)" if len(text) > 20000 else "")
    if name == "get_timeline":
        return timeline_summary(ctx.document)
    if name == "get_audio_analysis":
        return json.dumps(
            {"silence": ctx.silence, "filler": ctx.filler, "audio_stats": ctx.audio_stats},
            default=str,
        )[:20000]
    if name == "get_scene_metadata":
        return json.dumps(
            {
                "scenes": ctx.scenes[:80],
                "vision": {
                    k: (ctx.vision or {}).get(k) for k in ("scenes", "editing_opportunities")
                },
            },
            default=str,
        )[:20000]
    if name == "get_content_analysis":
        return (
            analysis_summary(ctx)
            if ctx.content
            else "No content analysis yet. Ask the user to run Analyze."
        )[:24000]
    if name == "plan_edit":
        planner = get_planner(ts.session, project_id=ctx.project.id, user_id=ts.user_id)
        result = planner.plan(
            ctx,
            PlanRequest(
                instruction=str(args.get("instruction", "")),
                target_platform=args.get("target_platform"),
                target_duration=_num(args.get("target_duration_seconds")),
            ),
        )
        ts.staged.extend(result.operations)
        ts.plan_summary = result.edl.summary
        ts.plan_delta = result.edl.estimated_duration_delta
        ts.warnings.extend(result.edl.warnings + result.notes)
        return json.dumps(
            {
                "summary": result.edl.summary,
                "operations_staged": len(result.operations),
                "rejected": len(result.rejected),
                "estimated_duration_delta": result.edl.estimated_duration_delta,
                "duration_after": result.duration_after,
                "warnings": result.edl.warnings,
                "notes": result.notes,
                "operation_types": _count_types(result.operations),
            }
        )
    if name == "remove_segment":
        segs = [
            {"start": float(s["start"]), "end": float(s["end"])}
            for s in args.get("segments", [])
            if float(s["end"]) > float(s["start"])
        ]
        if not segs:
            return "No valid segments."
        ts.staged.append(
            EditOperation(
                type="remove_segment",
                asset_id=asset_id,
                segments=segs,
                start=segs[0]["start"],
                end=segs[-1]["end"],
                reason=str(args.get("reason", "requested")),
                source="ai",
                confidence=0.9,
            )
        )
        return f"Staged removal of {len(segs)} segment(s), {sum(s['end'] - s['start'] for s in segs):.1f}s total."
    if name == "remove_silences":
        ts.staged.append(
            EditOperation(
                type="silence_removal",
                asset_id=asset_id,
                params={"auto": True, "min_duration": _num(args.get("min_duration"), 0.0) or 0.0},
                reason="Remove pauses",
                source="ai",
                confidence=0.95,
            )
        )
        return f"Staged: remove detected pauses ({(ctx.silence or {}).get('count', 0)} candidates, ~{(ctx.silence or {}).get('removable_seconds', 0)}s)."
    if name == "remove_filler_words":
        ts.staged.append(
            EditOperation(
                type="filler_word_removal",
                asset_id=asset_id,
                params={"auto": True},
                reason="Remove filler words",
                source="ai",
                confidence=0.9,
            )
        )
        return f"Staged: remove filler words ({(ctx.filler or {}).get('count', 0)} detected)."
    if name == "create_cut":
        ts.staged.append(
            EditOperation(
                type="split",
                asset_id=asset_id,
                timestamp=_num(args.get("timestamp"), 0.0) or 0.0,
                reason="Cut point",
                source="ai",
            )
        )
        return "Staged a cut."
    if name == "add_caption":
        if args.get("auto", True) and not args.get("text"):
            ts.staged.append(
                EditOperation(
                    type="caption",
                    asset_id=asset_id,
                    params={"auto": True, "style": {"preset": args.get("preset", "clean")}},
                    reason="Auto captions",
                    source="ai",
                )
            )
            return "Staged: auto captions from the transcript."
        ts.staged.append(
            EditOperation(
                type="caption",
                asset_id=asset_id,
                start=_num(args.get("start"), 0.0) or 0.0,
                end=_num(args.get("end"), 1.0) or 1.0,
                text=str(args.get("text", "")),
                reason="Caption",
                source="ai",
            )
        )
        return "Staged one caption."
    if name == "add_zoom":
        ts.staged.append(
            EditOperation(
                type="zoom",
                asset_id=asset_id,
                timestamp=_num(args.get("timestamp"), 0.0) or 0.0,
                duration=_num(args.get("duration"), 2.0) or 2.0,
                scale=min(1.4, max(1.02, _num(args.get("scale"), 1.12) or 1.12)),
                reason=str(args.get("reason", "emphasis")),
                source="ai",
                confidence=0.7,
            )
        )
        return "Staged a zoom."
    if name == "add_broll":
        ts.staged.append(
            EditOperation(
                type="insert_broll",
                asset_id=asset_id,
                timestamp=_num(args.get("timestamp"), 0.0) or 0.0,
                duration=_num(args.get("duration"), 4.0) or 4.0,
                query=str(args.get("query", "")),
                reason=str(args.get("reason", "")),
                source="ai",
                confidence=0.7,
            )
        )
        return "Staged a B-roll suggestion."
    if name == "reframe_clip":
        ts.staged.append(
            EditOperation(
                type="reframe",
                params={
                    "aspect_ratio": args.get("aspect_ratio", "9:16"),
                    "mode": args.get("mode", "track"),
                },
                reason="Reframe",
                source="ai",
            )
        )
        return f"Staged reframe to {args.get('aspect_ratio', '9:16')}."
    if name == "adjust_audio":
        n = 0
        if args.get("normalize"):
            ts.staged.append(
                EditOperation(type="normalize_audio", reason="Normalize loudness", source="ai")
            )
            n += 1
        if args.get("noise_reduction"):
            ts.staged.append(
                EditOperation(type="noise_reduction", reason="Reduce background noise", source="ai")
            )
            n += 1
        if args.get("voice_enhancement"):
            ts.staged.append(
                EditOperation(type="voice_enhancement", reason="Enhance voice", source="ai")
            )
            n += 1
        if args.get("gain_db") is not None:
            ts.staged.append(
                EditOperation(
                    type="audio_gain",
                    asset_id=asset_id,
                    start=0.0,
                    end=ctx.duration,
                    params={"gain_db": _num(args.get("gain_db"), 0.0)},
                    reason="Gain",
                    source="ai",
                )
            )
            n += 1
        return f"Staged {n} audio adjustment(s)."
    if name == "create_short":
        ts.side_effects.append(
            {
                "kind": "shorts",
                "count": int(args.get("count", 3)),
                "duration": int(args.get("duration_seconds", 45)),
                "platform": args.get("platform"),
            }
        )
        return "Short generation will start when the user confirms (it appears as a job)."
    if name == "render_video":
        ts.side_effects.append({"kind": "render", "preset": args.get("preset", "youtube_1080p")})
        return "Render will start when the user confirms."
    return f"Unknown tool {name}"


def _count_types(ops: list[EditOperation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for op in ops:
        counts[op.type] = counts.get(op.type, 0) + 1
    return counts
