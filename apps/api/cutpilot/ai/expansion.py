"""Expand macro operations into concrete, deterministic operations using stored analysis.

The planner may say "remove all silences" (`silence_removal` with params.auto) or "add captions"
(`caption` with params.auto). Those are expanded here from the silence/filler analysis and the
transcript's word timestamps — never by the LLM — so results are exact and reproducible.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cutpilot.db.models import (
    AnalysisResult,
    Speaker,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)
from cutpilot.timeline.model import merge_ranges
from cutpilot.timeline.operations import EditOperation


def latest_result(session: Session, asset_id: uuid.UUID, kind: str) -> AnalysisResult | None:
    return (
        session.execute(
            select(AnalysisResult)
            .where(AnalysisResult.asset_id == asset_id, AnalysisResult.kind == kind)
            .order_by(AnalysisResult.created_at.desc())
        )
        .scalars()
        .first()
    )


def current_transcript(
    session: Session, project_id: uuid.UUID, asset_id: uuid.UUID
) -> Transcript | None:
    return (
        session.execute(
            select(Transcript)
            .where(
                Transcript.project_id == project_id,
                Transcript.asset_id == asset_id,
                Transcript.is_current.is_(True),
            )
            .order_by(Transcript.created_at.desc())
        )
        .scalars()
        .first()
    )


def transcript_words(session: Session, transcript: Transcript) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    speakers = {
        s.id: s
        for s in session.execute(select(Speaker).where(Speaker.transcript_id == transcript.id))
        .scalars()
        .all()
    }
    for seg in (
        session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == transcript.id)
            .order_by(TranscriptSegment.index)
        )
        .scalars()
        .all()
    ):
        for w in (
            session.execute(
                select(TranscriptWord)
                .where(TranscriptWord.segment_id == seg.id)
                .order_by(TranscriptWord.index)
            )
            .scalars()
            .all()
        ):
            spk = speakers.get(w.speaker_id or seg.speaker_id)  # type: ignore[arg-type]
            words.append(
                {
                    "start": w.start,
                    "end": w.end,
                    "text": w.text,
                    "is_filler": w.is_filler,
                    "segment_end": seg.end,
                    "speaker": spk.display_name if spk else None,
                }
            )
    return words


def build_caption_cues(
    words: list[dict[str, Any]],
    *,
    max_words: int = 6,
    max_duration: float = 4.0,
    max_gap: float = 0.8,
    skip_fillers: bool = True,
) -> list[dict[str, Any]]:
    """Group words into caption cues. Cues break on sentence ends, long gaps, word count or duration."""
    cues: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        start, end = current[0]["start"], current[-1]["end"]
        text = " ".join(w["text"] for w in current)
        cues.append(
            {
                "start": round(start, 3),
                "end": round(max(end, start + 0.3), 3),
                "text": text,
                "speaker": current[0].get("speaker"),
                "words": [
                    {
                        "text": w["text"],
                        "start": round(w["start"] - start, 3),
                        "end": round(w["end"] - start, 3),
                    }
                    for w in current
                ],
            }
        )

    for w in words:
        if skip_fillers and w.get("is_filler"):
            continue
        if current:
            gap = w["start"] - current[-1]["end"]
            span = w["end"] - current[0]["start"]
            ends_sentence = current[-1]["text"].rstrip().endswith((".", "?", "!"))
            if len(current) >= max_words or span > max_duration or gap > max_gap or ends_sentence:
                flush()
                current = []
        current.append(w)
    flush()
    return cues


def expand_operations(
    session: Session,
    *,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    operations: list[EditOperation],
    caption_style: dict[str, Any] | None = None,
) -> tuple[list[EditOperation], list[str]]:
    """Replace macro ops with concrete ones. Returns (operations, notes)."""
    out: list[EditOperation] = []
    notes: list[str] = []
    for op in operations:
        auto = bool(op.params.get("auto"))
        target = uuid.UUID(op.asset_id) if op.asset_id else asset_id
        if op.type == "silence_removal" and auto:
            res = latest_result(session, target, "silence")
            cuts = res.data.get("suggested_cuts", []) if res else []
            min_len = float(op.params.get("min_duration", 0.0))
            segs = [
                {"start": c["start"], "end": c["end"], "label": "silence"}
                for c in cuts
                if c["end"] - c["start"] >= min_len
            ]
            if not segs:
                notes.append("No silences matched the criteria; nothing to remove.")
                continue
            out.append(
                op.model_copy(
                    update={
                        "asset_id": str(target),
                        "segments": segs,
                        "start": None,
                        "end": None,
                        "reason": op.reason or f"Remove {len(segs)} pauses",
                        "params": {**op.params, "auto": False, "expanded_from": "silence"},
                    }
                )
            )
        elif op.type == "filler_word_removal" and auto:
            res = latest_result(session, target, "filler")
            segs = [
                {"start": s["start"], "end": s["end"], "label": s.get("text", "filler")}
                for s in (res.data.get("segments", []) if res else [])
            ]
            if not segs:
                notes.append("No filler words detected; nothing to remove.")
                continue
            out.append(
                op.model_copy(
                    update={
                        "asset_id": str(target),
                        "segments": segs,
                        "start": None,
                        "end": None,
                        "reason": op.reason or f"Remove {len(segs)} filler words",
                        "params": {**op.params, "auto": False, "expanded_from": "filler"},
                    }
                )
            )
        elif op.type in ("caption", "subtitle") and auto:
            transcript = current_transcript(session, project_id, target)
            if transcript is None:
                notes.append("Captions need a transcript; transcribe the footage first.")
                continue
            style = {**(caption_style or {}), **op.params.get("style", {})}
            cues = build_caption_cues(
                transcript_words(session, transcript),
                max_words=int(style.get("max_words_per_cue", op.params.get("max_words", 6))),
            )
            for cue in cues:
                out.append(
                    EditOperation(
                        type="caption",
                        asset_id=str(target),
                        time_ref="source",
                        start=cue["start"],
                        end=cue["end"],
                        text=cue["text"],
                        params={
                            "words": cue["words"],
                            "style": op.params.get("style", {}),
                            "speaker": cue["speaker"],
                            "expanded_from": "auto_captions",
                        },
                        confidence=op.confidence,
                        reason=op.reason or "Auto captions",
                        source=op.source,
                    )
                )
            notes.append(f"Generated {len(cues)} caption cues from the transcript.")
        elif op.type == "remove_segment" and op.segments:
            merged = merge_ranges([(float(s["start"]), float(s["end"])) for s in op.segments])
            out.append(
                op.model_copy(
                    update={
                        "asset_id": op.asset_id or str(target),
                        "segments": [{"start": a, "end": b} for a, b in merged],
                    }
                )
            )
        else:
            if (
                op.asset_id is None
                and op.time_ref == "source"
                and op.type
                not in (
                    "set_track_state",
                    "reframe",
                    "normalize_audio",
                    "noise_reduction",
                    "voice_enhancement",
                    "music",
                    "insert_audio",
                    "delete_clip",
                    "trim",
                    "move_clip",
                    "merge",
                    "reorder",
                    "mute",
                )
            ):
                op = op.model_copy(update={"asset_id": str(target)})
            out.append(op)
    return out, notes


def estimate_duration_delta(operations: list[EditOperation]) -> float:
    delta = 0.0
    for op in operations:
        if op.type in ("remove_segment", "silence_removal", "filler_word_removal", "jump_cut"):
            if op.segments:
                delta -= sum(float(s["end"]) - float(s["start"]) for s in op.segments)
            elif op.start is not None and op.end is not None:
                delta -= op.end - op.start
        elif op.type == "speed_change" and op.start is not None and op.end is not None:
            speed = float(op.params.get("speed", 1.0))
            if speed > 0:
                delta -= (op.end - op.start) * (1 - 1 / speed)
    return round(delta, 3)
