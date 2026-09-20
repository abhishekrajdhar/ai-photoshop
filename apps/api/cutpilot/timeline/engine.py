"""Deterministic timeline operation engine.

`apply_operations(doc, ops)` returns a *new* document; the input is never mutated.
All time arithmetic lives here so it can be unit-tested without media or an LLM.
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field

from cutpilot.timeline.model import (
    Clip,
    Effect,
    Marker,
    TimelineDocument,
    Track,
    Transition,
    merge_ranges,
    new_id,
)
from cutpilot.timeline.operations import EditOperation

EPS = 1e-4


@dataclass
class ApplyResult:
    document: TimelineDocument
    applied: list[EditOperation] = field(default_factory=list)
    rejected: list[tuple[EditOperation, str]] = field(default_factory=list)

    @property
    def duration_delta(self) -> float:
        return 0.0


class OperationError(ValueError):
    pass


# ── primitive edits ─────────────────────────────────────────────────────────


def split_clip(clip: Clip, at: float) -> tuple[Clip, Clip] | None:
    """Split a clip at absolute timeline time `at`. Returns (left, right) or None if outside."""
    if at <= clip.timeline_start + EPS or at >= clip.timeline_end - EPS:
        return None
    left = clip.model_copy(deep=True)
    right = clip.model_copy(deep=True)
    right.id = new_id("clip")
    offset = at - clip.timeline_start

    left.duration = round(offset, 6)
    right.timeline_start = round(at, 6)
    right.duration = round(clip.duration - offset, 6)
    if clip.asset_id and clip.kind in ("video", "audio", "broll", "music") and not clip.loop:
        src_split = clip.timeline_to_source(at)
        left.source_out = round(src_split, 6)
        right.source_in = round(src_split, 6)
    if clip.words:
        left.words = [w for w in clip.words if w["start"] < offset]
        right.words = [
            {**w, "start": round(w["start"] - offset, 6), "end": round(w["end"] - offset, 6)}
            for w in clip.words
            if w["start"] >= offset
        ]
    if clip.text is not None and clip.words:
        left.text = " ".join(w["text"] for w in left.words) or left.text
        right.text = " ".join(w["text"] for w in right.words) or right.text

    left.effects, right.effects = [], []
    for fx in clip.effects:
        fx_start = fx.start or 0.0
        fx_end = fx_start + (fx.duration if fx.duration is not None else clip.duration - fx_start)
        if fx_end <= offset + EPS:
            left.effects.append(fx)
        elif fx_start >= offset - EPS:
            moved = fx.model_copy(deep=True)
            moved.start = round(fx_start - offset, 6)
            right.effects.append(moved)
        else:
            l_fx = fx.model_copy(deep=True)
            l_fx.duration = round(offset - fx_start, 6) if fx.duration is not None else None
            r_fx = fx.model_copy(deep=True)
            r_fx.id = new_id("fx")
            r_fx.start = 0.0
            r_fx.duration = round(fx_end - offset, 6) if fx.duration is not None else None
            left.effects.append(l_fx)
            right.effects.append(r_fx)
    left.transition_out = Transition()
    right.transition_in = Transition()
    left.fade_out, right.fade_in = 0.0, 0.0
    return left, right


def _relink_pieces(
    doc: TimelineDocument, pieces: dict[str, tuple[Clip | None, Clip | None]]
) -> None:
    """After splitting linked clips, point right-hand pieces at each other and drop dangling links."""
    existing = {c.id for _, c in doc.all_clips()}
    for _old_id, (_left, right) in pieces.items():
        if right is None:
            continue
        link = right.linked_clip_id
        if link in pieces:
            partner_right = pieces[link][1]
            right.linked_clip_id = partner_right.id if partner_right else None
        elif link is not None and link not in existing:
            right.linked_clip_id = None
    for _, c in doc.all_clips():
        if (
            c.linked_clip_id is not None
            and c.linked_clip_id not in existing
            and c.linked_clip_id not in {p[1].id for p in pieces.values() if p[1]}
        ):
            c.linked_clip_id = None


def remove_timeline_range(
    doc: TimelineDocument,
    start: float,
    end: float,
    *,
    ripple: bool = True,
    track_ids: set[str] | None = None,
) -> float:
    """Remove [start, end) from the timeline in place. Returns the removed duration."""
    start, end = max(0.0, start), max(0.0, end)
    if end - start <= EPS:
        return 0.0
    removed = end - start
    pieces_by_old: dict[str, tuple[Clip | None, Clip | None]] = {}
    for track in doc.tracks:
        if track_ids is not None and track.id not in track_ids:
            continue
        if track.locked:
            continue
        new_clips: list[Clip] = []
        for clip in track.sorted_clips():
            if clip.timeline_end <= start + EPS or clip.timeline_start >= end - EPS:
                new_clips.append(clip)
                continue
            # Overlapping: keep left part, right part
            old_id = clip.id
            left_piece: Clip | None = None
            right_piece: Clip | None = None
            pieces: list[Clip] = []
            if clip.timeline_start < start - EPS:
                res = split_clip(clip, start)
                if res:
                    left_piece, rest = res
                    pieces.append(left_piece)
                    clip = rest
            if clip.timeline_end > end + EPS:
                res = split_clip(clip, end)
                if res:
                    _, right_piece = res
                    pieces.append(right_piece)
            if right_piece is not None and left_piece is None:
                # The clip's id is kept by the *left* piece normally; with no left piece, keep the id on the right.
                right_piece.id = old_id
                pieces_by_old[old_id] = (None, None)
            else:
                pieces_by_old[old_id] = (left_piece, right_piece)
            new_clips.extend(pieces)
        if ripple:
            for clip in new_clips:
                if clip.timeline_start >= end - EPS:
                    clip.timeline_start = round(clip.timeline_start - removed, 6)
        track.clips = sorted(new_clips, key=lambda c: c.timeline_start)
    _relink_pieces(doc, pieces_by_old)
    if ripple:
        for m in doc.markers:
            if m.time >= end:
                m.time = round(m.time - removed, 6)
            elif m.time > start:
                m.time = round(start, 6)
    return removed


def insert_gap(
    doc: TimelineDocument, at: float, length: float, exclude_track: str | None = None
) -> None:
    for track in doc.tracks:
        if track.id == exclude_track or track.locked:
            continue
        for clip in track.clips:
            if clip.timeline_start >= at - EPS:
                clip.timeline_start = round(clip.timeline_start + length, 6)


def _ranges_for_op(
    doc: TimelineDocument, op: EditOperation, start: float, end: float
) -> list[tuple[float, float]]:
    """Resolve an operation's time range to timeline ranges."""
    if op.time_ref == "timeline":
        return [(start, end)]
    asset_id = op.asset_id
    if asset_id is None and op.source_clip_id:
        _, clip = doc.find_clip(op.source_clip_id)
        asset_id = clip.asset_id
    if asset_id is None:
        # No asset: interpret as timeline time (AI without asset context).
        return [(start, end)]
    return doc.source_to_timeline_ranges(asset_id, start, end, kinds=("video", "audio"))


def _resolve_point(doc: TimelineDocument, op: EditOperation, t: float) -> float | None:
    """Resolve a single timestamp (source or timeline) to a timeline time."""
    if op.time_ref == "timeline" or (op.asset_id is None and op.source_clip_id is None):
        return t
    asset_id = op.asset_id
    if asset_id is None and op.source_clip_id:
        _, clip = doc.find_clip(op.source_clip_id)
        asset_id = clip.asset_id
    if asset_id is None:
        return t
    for _, clip in doc.clips_for_asset(asset_id):
        if clip.source_in - EPS <= t < clip.source_out + EPS:
            return clip.source_to_timeline(t)
    return None


def _primary_video_clip_at(doc: TimelineDocument, t: float) -> Clip | None:
    for track in doc.tracks_of_kind("video"):
        clip = doc.clip_at(track, t)
        if clip:
            return clip
    return None


# ── operation handlers ──────────────────────────────────────────────────────


def _op_remove(doc: TimelineDocument, op: EditOperation) -> None:
    segments = op.segments or [{"start": op.start, "end": op.end}]
    ranges: list[tuple[float, float]] = []
    for seg in segments:
        s, e = float(seg["start"]), float(seg["end"])
        if e <= s:
            continue
        ranges.extend(_ranges_for_op(doc, op, s, e))
    if not ranges:
        raise OperationError("range is not on the timeline")
    # Remove from the end so earlier ranges are unaffected by ripple.
    for s, e in reversed(merge_ranges(ranges)):
        remove_timeline_range(doc, s, e, ripple=True)


def _op_split(doc: TimelineDocument, op: EditOperation) -> None:
    assert op.timestamp is not None
    at = _resolve_point(doc, op, op.timestamp)
    if at is None:
        raise OperationError("split point is not on the timeline")
    targets: list[tuple[Track, Clip]]
    if op.source_clip_id:
        track, clip = doc.find_clip(op.source_clip_id)
        targets = [(track, clip)]
        if clip.linked_clip_id:
            try:
                targets.append(doc.find_clip(clip.linked_clip_id))
            except KeyError:
                pass
    else:
        targets = [
            (t, c)
            for t, c in doc.all_clips()
            if c.timeline_start < at < c.timeline_end and not t.locked
        ]
    pieces: dict[str, tuple[Clip, Clip]] = {}
    for track, clip in targets:
        res = split_clip(clip, at)
        if res is None:
            continue
        left, right = res
        pieces[clip.id] = (left, right)
        track.clips = [c for c in track.clips if c.id != clip.id] + [left, right]
    # Re-link right-hand pieces to each other (left pieces keep the original ids/links).
    for _left, right in pieces.values():
        if right.linked_clip_id in pieces:
            right.linked_clip_id = pieces[right.linked_clip_id][1].id
        elif right.linked_clip_id is not None:
            right.linked_clip_id = None
    doc.sort()


def _op_trim(doc: TimelineDocument, op: EditOperation) -> None:
    if not op.source_clip_id:
        raise OperationError("trim requires source_clip_id")
    track, clip = doc.find_clip(op.source_clip_id)
    _trim_clip(doc, track, clip, op)
    if clip.linked_clip_id and not op.params.get("unlink"):
        try:
            l_track, linked = doc.find_clip(clip.linked_clip_id)
        except KeyError:
            return
        _trim_clip(doc, l_track, linked, op)


def _trim_clip(doc: TimelineDocument, track: Track, clip: Clip, op: EditOperation) -> None:
    side = op.params.get("side", "out")
    new_start = op.params.get("timeline_start")
    new_end = op.params.get("timeline_end")
    ripple = bool(op.params.get("ripple", False))
    old_start, old_end = clip.timeline_start, clip.timeline_end
    if side == "in" and new_start is not None:
        new_start = max(
            min(float(new_start), old_end - 0.05),
            old_start - clip.source_in / max(clip.speed, 1e-6),
        )
        delta = new_start - old_start
        clip.source_in = round(clip.source_in + delta * clip.speed, 6)
        clip.timeline_start = round(new_start, 6)
        clip.duration = round(old_end - new_start, 6)
    elif side == "out" and new_end is not None:
        new_end = max(float(new_end), old_start + 0.05)
        clip.source_out = round(clip.timeline_to_source(new_end), 6)
        clip.duration = round(new_end - old_start, 6)
    else:
        raise OperationError("trim requires side and timeline_start/timeline_end")
    if ripple:
        shift = clip.timeline_end - old_end
        for c in track.clips:
            if c.id != clip.id and c.timeline_start >= old_end - EPS:
                c.timeline_start = round(c.timeline_start + shift, 6)
    doc.sort()


def _op_delete_clip(doc: TimelineDocument, op: EditOperation) -> None:
    if not op.source_clip_id:
        raise OperationError("delete_clip requires source_clip_id")
    track, clip = doc.find_clip(op.source_clip_id)
    ripple = bool(op.params.get("ripple", True))
    # Resolve the linked partner up-front (links are cleared once a clip disappears).
    partner: tuple[Track, Clip] | None = None
    if clip.linked_clip_id:
        try:
            partner = doc.find_clip(clip.linked_clip_id)
        except KeyError:
            partner = None
    targets = [(track, clip)] + ([partner] if partner else [])
    for t, c in targets:
        if ripple:
            remove_timeline_range(
                doc, c.timeline_start, c.timeline_end, ripple=True, track_ids={t.id}
            )
        else:
            t.clips = [x for x in t.clips if x.id != c.id]
    if ripple and op.params.get("ripple_all", False):
        touched = {t.id for t, _ in targets}
        for t in doc.tracks:
            if t.id in touched:
                continue
            for c in t.clips:
                if c.timeline_start >= clip.timeline_end - EPS:
                    c.timeline_start = round(c.timeline_start - clip.duration, 6)
    doc.sort()


def _merge_clips(doc: TimelineDocument, clips: list[Clip]) -> Clip:
    """Merge adjacent, continuous clips from the same source into one (in place on their track)."""
    clips = sorted(clips, key=lambda c: c.timeline_start)
    track = doc.find_clip(clips[0].id)[0]
    for a, b in itertools.pairwise(clips):
        contiguous = (
            abs(a.timeline_end - b.timeline_start) < 0.01 and abs(a.source_out - b.source_in) < 0.05
        )
        if a.asset_id != b.asset_id or not contiguous or a.speed != b.speed:
            raise OperationError("clips must be adjacent and continuous to merge")
    merged = clips[0].model_copy(deep=True)
    merged.source_out = clips[-1].source_out
    merged.duration = round(clips[-1].timeline_end - clips[0].timeline_start, 6)
    merged.transition_out = clips[-1].transition_out
    merged.fade_out = clips[-1].fade_out
    for extra in clips[1:]:
        off = extra.timeline_start - merged.timeline_start
        for fx in extra.effects:
            moved = fx.model_copy(deep=True)
            moved.start = round((fx.start or 0.0) + off, 6)
            merged.effects.append(moved)
    keep = {c.id for c in clips}
    track.clips = [c for c in track.clips if c.id not in keep] + [merged]
    return merged


def _op_merge(doc: TimelineDocument, op: EditOperation) -> None:
    ids = op.params.get("clip_ids") or ([op.source_clip_id] if op.source_clip_id else [])
    if len(ids) < 2:
        raise OperationError("merge requires at least two clip_ids")
    clips = [doc.find_clip(i)[1] for i in ids]
    merged = _merge_clips(doc, clips)
    # Merge linked clips (e.g. the audio that belongs to merged video) when they are contiguous.
    linked_ids = [c.linked_clip_id for c in clips if c.linked_clip_id]
    if len(linked_ids) == len(clips):
        try:
            linked = [doc.find_clip(i)[1] for i in linked_ids]
            merged_linked = _merge_clips(doc, linked)
            merged.linked_clip_id = merged_linked.id
            merged_linked.linked_clip_id = merged.id
        except (KeyError, OperationError):
            pass
    doc.sort()


def _op_move(doc: TimelineDocument, op: EditOperation) -> None:
    if not op.source_clip_id:
        raise OperationError("move_clip requires source_clip_id")
    track, clip = doc.find_clip(op.source_clip_id)
    target_track_id = op.params.get("track_id") or op.track_id or track.id
    new_start = float(
        op.params.get(
            "timeline_start", op.timestamp if op.timestamp is not None else clip.timeline_start
        )
    )
    target = doc.track(target_track_id)
    if target.kind != track.kind and not (
        target.kind == "video" and clip.kind in ("video", "image", "broll")
    ):
        raise OperationError("cannot move clip to a track of a different kind")
    track.clips = [c for c in track.clips if c.id != clip.id]
    clip.timeline_start = round(max(0.0, new_start), 6)
    # Simple overlap handling: push overlapping clips on target to the right.
    for other in target.sorted_clips():
        if other.timeline_start < clip.timeline_end and other.timeline_end > clip.timeline_start:
            other.timeline_start = round(clip.timeline_end, 6)
    target.clips.append(clip)
    doc.sort()


def _op_reorder(doc: TimelineDocument, op: EditOperation) -> None:
    if not op.source_clip_id:
        raise OperationError("reorder requires source_clip_id")
    track, clip = doc.find_clip(op.source_clip_id)
    new_index = int(op.params.get("index", 0))
    ordered = [c for c in track.sorted_clips() if c.id != clip.id]
    ordered.insert(max(0, min(new_index, len(ordered))), clip)
    t = 0.0
    for c in ordered:
        c.timeline_start = round(t, 6)
        t += c.duration
    track.clips = ordered


def _apply_effect_over_range(
    doc: TimelineDocument, op: EditOperation, effect_type: str, params: dict, kinds: tuple[str, ...]
) -> None:  # type: ignore[type-arg]
    """Attach an effect to all clips of `kinds` overlapping the op's range (whole clip if no range)."""
    if op.source_clip_id and op.start is None:
        _, clip = doc.find_clip(op.source_clip_id)
        clip.effects.append(Effect(type=effect_type, params=params))  # type: ignore[arg-type]
        return
    if op.start is None or op.end is None:
        # Whole timeline
        for _t, c in doc.all_clips():
            if c.kind in kinds:
                c.effects.append(Effect(type=effect_type, params=params))  # type: ignore[arg-type]
        return
    for s, e in _ranges_for_op(doc, op, op.start, op.end):
        for _t, c in doc.all_clips():
            if c.kind not in kinds:
                continue
            a, b = max(s, c.timeline_start), min(e, c.timeline_end)
            if b - a > EPS:
                c.effects.append(
                    Effect(
                        type=effect_type,
                        start=round(a - c.timeline_start, 6),
                        duration=round(b - a, 6),
                        params=params,
                    )  # type: ignore[arg-type]
                )


def _op_zoom(doc: TimelineDocument, op: EditOperation) -> None:
    t0 = op.effective_start()
    at = _resolve_point(doc, op, t0)
    if at is None:
        raise OperationError("zoom point is not on the timeline")
    clip = _primary_video_clip_at(doc, at)
    if clip is None:
        raise OperationError("no video clip at zoom point")
    duration = op.duration or (
        op.end - op.start if op.end is not None and op.start is not None else 2.0
    )
    duration = max(0.3, min(duration, clip.timeline_end - at))
    params = {
        "scale": op.scale or float(op.params.get("scale", 1.12)),
        "anchor": op.params.get("anchor", "center"),
        "ease": op.params.get("ease", "in_out"),
        "x": op.params.get("x", 0.5),
        "y": op.params.get("y", 0.5),
    }
    clip.effects.append(
        Effect(
            type="zoom",
            start=round(at - clip.timeline_start, 6),
            duration=round(duration, 6),
            params=params,
        )
    )


def _op_caption(doc: TimelineDocument, op: EditOperation) -> None:
    assert op.start is not None and op.end is not None and op.text
    track = doc.caption_track()
    # Captions follow the picture: map through video tracks first, audio only for audio-only sequences.
    ranges = _caption_ranges(doc, op)
    if not ranges:
        raise OperationError("caption range is not on the timeline")
    s, e = ranges[0][0], ranges[-1][1]
    # Never stack captions: clamp against neighbours instead of deleting them.
    for other in track.sorted_clips():
        if other.timeline_end <= s + EPS or other.timeline_start >= e - EPS:
            continue
        if other.timeline_start <= s:
            s = max(s, other.timeline_end)
        else:
            e = min(e, other.timeline_start)
    if e - s < 0.25:
        raise OperationError("caption is too short after cuts / overlaps")
    style = dict(op.params.get("style", {}))
    words = op.params.get("words")
    clip = Clip(
        kind="caption",
        name=op.text[:40],
        timeline_start=round(s, 6),
        duration=round(e - s, 6),
        source_in=0.0,
        source_out=round(e - s, 6),
        text=op.text,
        words=words,
        style=style,
        meta={"speaker": op.params.get("speaker")},
    )
    track.clips.append(clip)
    doc.sort()


def _caption_ranges(doc: TimelineDocument, op: EditOperation) -> list[tuple[float, float]]:
    assert op.start is not None and op.end is not None
    if op.time_ref == "timeline":
        return [(op.start, op.end)]
    asset_id = op.asset_id
    if asset_id is None and op.source_clip_id:
        asset_id = doc.find_clip(op.source_clip_id)[1].asset_id
    if asset_id is None:
        return [(op.start, op.end)]
    ranges = doc.source_to_timeline_ranges(asset_id, op.start, op.end, kinds=("video",))
    if not ranges:
        ranges = doc.source_to_timeline_ranges(asset_id, op.start, op.end, kinds=("audio",))
    return ranges


def _overlay_track(doc: TimelineDocument) -> Track:
    tracks = doc.tracks_of_kind("overlay")
    if tracks:
        return tracks[0]
    track = Track(id="O1", kind="overlay", name="Overlays", index=len(doc.tracks))
    doc.tracks.append(track)
    return track


def _op_text_overlay(doc: TimelineDocument, op: EditOperation) -> None:
    assert op.start is not None and op.end is not None and op.text
    ranges = _ranges_for_op(doc, op, op.start, op.end)
    if not ranges:
        raise OperationError("text overlay range is not on the timeline")
    s, e = ranges[0][0], ranges[-1][1]
    track = _overlay_track(doc)
    track.clips.append(
        Clip(
            kind="text",
            name=op.text[:40],
            timeline_start=round(s, 6),
            duration=round(e - s, 6),
            source_out=round(e - s, 6),
            text=op.text,
            style=dict(op.params.get("style", {})),
            position=op.params.get("position") or {"x": 0.5, "y": 0.15, "w": 0.8, "h": 0.1},
        )
    )
    doc.sort()


def _op_insert_visual(doc: TimelineDocument, op: EditOperation) -> None:
    """insert_broll / insert_image / image_overlay: place on the second video track."""
    at = _resolve_point(doc, op, op.effective_start())
    if at is None:
        raise OperationError("insert point is not on the timeline")
    duration = op.duration or float(op.params.get("duration", 4.0))
    video_tracks = doc.tracks_of_kind("video")
    track = video_tracks[1] if len(video_tracks) > 1 else video_tracks[0]
    if op.type == "image_overlay":
        track = _overlay_track(doc)
    kind = "image" if op.type in ("insert_image", "image_overlay") else "broll"
    clip = Clip(
        kind=kind,
        name=op.query or op.params.get("name", kind),
        asset_id=op.asset_id
        if op.type != "insert_broll" or op.params.get("asset_is_broll")
        else op.params.get("broll_asset_id"),
        timeline_start=round(at, 6),
        duration=round(duration, 6),
        source_in=float(op.params.get("source_in", 0.0)),
        source_out=float(op.params.get("source_in", 0.0)) + duration,
        position=op.params.get("position"),
        muted=True,
        meta={
            "query": op.query,
            "reason": op.reason,
            "confidence": op.confidence,
            "suggested": op.params.get("broll_asset_id") is None and kind == "broll",
        },
    )
    if kind == "broll" and clip.asset_id is None:
        # No matching media yet: record as a suggestion marker rather than an empty clip.
        doc.markers.append(
            Marker(
                time=round(at, 6),
                label=f"B-roll: {op.query or ''}",
                kind="broll_suggestion",
                meta={
                    "query": op.query,
                    "duration": duration,
                    "reason": op.reason,
                    "confidence": op.confidence,
                },
            )
        )
        return
    # Avoid overlaps on the B-roll track
    track.clips = [
        c
        for c in track.clips
        if not (c.timeline_start < clip.timeline_end and c.timeline_end > clip.timeline_start)
    ]
    track.clips.append(clip)
    doc.sort()


def _op_insert_audio(doc: TimelineDocument, op: EditOperation) -> None:
    if not op.asset_id:
        raise OperationError(f"{op.type} requires asset_id")
    at = (
        op.effective_start()
        if op.time_ref == "timeline"
        else (_resolve_point(doc, op, op.effective_start()) or 0.0)
    )
    audio_tracks = doc.tracks_of_kind("audio")
    track = audio_tracks[1] if len(audio_tracks) > 1 else audio_tracks[0]
    duration = op.duration or float(op.params.get("duration", max(doc.duration() - at, 1.0)))
    src_dur = float(op.params.get("source_duration", duration))
    clip = Clip(
        kind="music" if op.type == "music" else "audio",
        name=op.params.get("name", "Music" if op.type == "music" else "Audio"),
        asset_id=op.asset_id,
        timeline_start=round(at, 6),
        duration=round(duration, 6),
        source_in=float(op.params.get("source_in", 0.0)),
        source_out=float(op.params.get("source_in", 0.0)) + min(src_dur, duration)
        if not op.params.get("loop")
        else src_dur,
        gain_db=float(op.params.get("gain_db", -18.0 if op.type == "music" else 0.0)),
        loop=bool(op.params.get("loop", op.type == "music")),
        fade_in=float(op.params.get("fade_in", 1.0 if op.type == "music" else 0.0)),
        fade_out=float(op.params.get("fade_out", 2.0 if op.type == "music" else 0.0)),
        ducking=bool(op.params.get("ducking", op.type == "music")),
    )
    track.clips.append(clip)
    doc.sort()


def _op_speed(doc: TimelineDocument, op: EditOperation) -> None:
    speed = float(op.params.get("speed", op.scale or 1.0))
    if speed <= 0:
        raise OperationError("speed must be > 0")
    if op.source_clip_id and op.start is None:
        targets = [doc.find_clip(op.source_clip_id)]
    else:
        assert op.start is not None and op.end is not None
        ranges = _ranges_for_op(doc, op, op.start, op.end)
        targets = []
        for s, e in ranges:
            for track in doc.tracks:
                if track.kind not in ("video", "audio"):
                    continue
                for clip in list(track.clips):
                    if clip.timeline_start < e and clip.timeline_end > s and clip.asset_id:
                        # split to isolate the range
                        pieces = [clip]
                        out: list[Clip] = []
                        for c in pieces:
                            r = split_clip(c, s)
                            if r:
                                out.append(r[0])
                                c = r[1]
                            r2 = split_clip(c, e)
                            if r2:
                                out.append(r2[0])
                                out.append(r2[1])
                                targets.append((track, r2[0]))
                            else:
                                out.append(c)
                                targets.append((track, c))
                        track.clips = [x for x in track.clips if x.id != clip.id] + out
        doc.sort()
    for _track, clip in targets:
        old_dur = clip.duration
        clip.speed = speed
        clip.recompute_duration()
        shift = clip.duration - old_dur
        for t in doc.tracks:
            for c in t.clips:
                if c.id != clip.id and c.timeline_start >= clip.timeline_start + old_dur - EPS:
                    c.timeline_start = round(c.timeline_start + shift, 6)
    doc.sort()


def _op_transition(doc: TimelineDocument, op: EditOperation) -> None:
    kind = op.params.get("kind", "crossfade")
    duration = float(op.params.get("duration", op.duration or 0.5))
    position = op.params.get("position", "out")
    if op.source_clip_id:
        _, clip = doc.find_clip(op.source_clip_id)
    else:
        at = _resolve_point(doc, op, op.effective_start())
        if at is None:
            raise OperationError("transition point is not on the timeline")
        clip = _primary_video_clip_at(doc, max(0.0, at - 0.01)) or _primary_video_clip_at(doc, at)
        if clip is None:
            raise OperationError("no clip at transition point")
    tr = Transition(type=kind, duration=duration)
    if position == "in":
        clip.transition_in = tr
    else:
        clip.transition_out = tr


def _op_fade(doc: TimelineDocument, op: EditOperation) -> None:
    position = op.params.get("position", "out")
    duration = float(op.params.get("duration", op.duration or 1.0))
    kinds = ("video", "image", "broll") if op.type == "fade_video" else ("audio", "music", "video")
    if op.source_clip_id:
        targets = [doc.find_clip(op.source_clip_id)[1]]
    else:
        targets = [c for _, c in doc.all_clips() if c.kind in kinds]
        # Fade the first / last clip on the primary track
        vt = (
            doc.primary_video_track().sorted_clips()
            if op.type == "fade_video"
            else doc.primary_audio_track().sorted_clips()
        )
        targets = [vt[0]] if position == "in" and vt else ([vt[-1]] if vt else targets)
    for clip in targets:
        if op.type == "fade_video":
            clip.effects.append(
                Effect(type="fade_video", params={"position": position, "duration": duration})
            )
        else:
            if position == "in":
                clip.fade_in = duration
            else:
                clip.fade_out = duration


def _op_audio_gain(doc: TimelineDocument, op: EditOperation) -> None:
    gain = float(op.params.get("gain_db", 0.0))
    if op.source_clip_id and op.start is None:
        _, clip = doc.find_clip(op.source_clip_id)
        clip.gain_db = gain
        return
    _apply_effect_over_range(doc, op, "audio_gain", {"gain_db": gain}, ("audio", "music", "video"))


def _op_mute(doc: TimelineDocument, op: EditOperation) -> None:
    muted = bool(op.params.get("muted", True))
    if op.track_id:
        doc.track(op.track_id).muted = muted
    elif op.source_clip_id:
        doc.find_clip(op.source_clip_id)[1].muted = muted
    else:
        raise OperationError("mute requires track_id or source_clip_id")


def _op_audio_process(doc: TimelineDocument, op: EditOperation) -> None:
    key = op.type  # noise_reduction | voice_enhancement | normalize_audio
    if op.source_clip_id or (op.start is not None and op.end is not None):
        _apply_effect_over_range(doc, op, key, dict(op.params), ("audio", "video"))
    else:
        doc.settings.audio[key] = {"enabled": True, **op.params}


def _op_color(doc: TimelineDocument, op: EditOperation) -> None:
    params = dict(op.params)
    if op.type in ("brightness", "contrast", "saturation"):
        params = {op.type: float(op.params.get("value", op.scale or 1.0))}
        effect_type = "color_adjustment"
    elif op.type == "lut":
        effect_type = "lut"
    else:
        effect_type = "color_adjustment"
    _apply_effect_over_range(doc, op, effect_type, params, ("video", "image", "broll"))


def _op_blur(doc: TimelineDocument, op: EditOperation) -> None:
    _apply_effect_over_range(doc, op, op.type, dict(op.params), ("video", "broll", "image"))


def _op_stabilize(doc: TimelineDocument, op: EditOperation) -> None:
    _apply_effect_over_range(doc, op, "stabilization", dict(op.params), ("video",))


def _op_crop(doc: TimelineDocument, op: EditOperation) -> None:
    _apply_effect_over_range(doc, op, "crop", dict(op.params), ("video", "broll", "image"))


def _op_reframe(doc: TimelineDocument, op: EditOperation) -> None:
    aspect = op.params.get("aspect_ratio", "9:16")
    mode = op.params.get("mode", "track")
    w, h = _aspect_dims(aspect, doc.settings.width, doc.settings.height)
    doc.settings.aspect_ratio = aspect
    doc.settings.width, doc.settings.height = w, h
    doc.settings.reframe = {
        "mode": mode,
        "source_aspect": op.params.get("source_aspect", "16:9"),
        "keyframes": op.params.get("keyframes", []),
    }


def _aspect_dims(aspect: str, width: int, height: int) -> tuple[int, int]:
    table = {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "4:3": (1440, 1080),
    }
    if aspect in table:
        return table[aspect]
    try:
        a, b = (float(x) for x in aspect.split(":"))
        return (int(round(height * a / b / 2) * 2), height)
    except ValueError:
        return width, height


def _op_track_state(doc: TimelineDocument, op: EditOperation) -> None:
    if not op.track_id:
        raise OperationError("set_track_state requires track_id")
    track = doc.track(op.track_id)
    for key in ("muted", "locked", "hidden"):
        if key in op.params:
            setattr(track, key, bool(op.params[key]))
    if "name" in op.params:
        track.name = str(op.params["name"])[:80]


def _op_marker(doc: TimelineDocument, op: EditOperation) -> None:
    at = _resolve_point(doc, op, op.effective_start())
    if at is None:
        raise OperationError("marker point is not on the timeline")
    doc.markers.append(
        Marker(
            time=round(at, 6),
            label=op.text or op.params.get("label", ""),
            kind=op.params.get("kind", "marker"),
            meta=op.params,
        )
    )


HANDLERS = {
    "remove_segment": _op_remove,
    "jump_cut": _op_remove,
    "silence_removal": _op_remove,
    "filler_word_removal": _op_remove,
    "cut": _op_split,
    "split": _op_split,
    "trim": _op_trim,
    "delete_clip": _op_delete_clip,
    "merge": _op_merge,
    "move_clip": _op_move,
    "reorder": _op_reorder,
    "speed_change": _op_speed,
    "transition": _op_transition,
    "zoom": _op_zoom,
    "crop": _op_crop,
    "reframe": _op_reframe,
    "caption": _op_caption,
    "subtitle": _op_caption,
    "text_overlay": _op_text_overlay,
    "image_overlay": _op_insert_visual,
    "insert_broll": _op_insert_visual,
    "insert_image": _op_insert_visual,
    "insert_audio": _op_insert_audio,
    "music": _op_insert_audio,
    "audio_gain": _op_audio_gain,
    "mute": _op_mute,
    "noise_reduction": _op_audio_process,
    "voice_enhancement": _op_audio_process,
    "normalize_audio": _op_audio_process,
    "fade_audio": _op_fade,
    "fade_video": _op_fade,
    "blur": _op_blur,
    "object_blur": _op_blur,
    "face_blur": _op_blur,
    "color_adjustment": _op_color,
    "brightness": _op_color,
    "contrast": _op_color,
    "saturation": _op_color,
    "lut": _op_color,
    "stabilization": _op_stabilize,
    "set_track_state": _op_track_state,
    "add_marker": _op_marker,
}


def apply_operations(
    doc: TimelineDocument, ops: list[EditOperation], *, strict: bool = False
) -> ApplyResult:
    """Apply operations in order, returning a new document. Invalid ops are rejected, not fatal."""
    working = doc.model_copy(deep=True)
    result = ApplyResult(document=working)
    for op in ops:
        handler = HANDLERS.get(op.type)
        if handler is None:
            result.rejected.append((op, f"unsupported operation {op.type}"))
            continue
        snapshot = copy.deepcopy(working.model_dump())
        try:
            handler(working, op)
            working.sort()
            result.applied.append(op)
        except (OperationError, KeyError, AssertionError, ValueError, TypeError) as exc:
            # Roll back this op only
            restored = TimelineDocument.model_validate(snapshot)
            working.tracks, working.markers, working.settings = (
                restored.tracks,
                restored.markers,
                restored.settings,
            )
            result.rejected.append((op, str(exc) or exc.__class__.__name__))
            if strict:
                raise
    return result


def add_source_clip(
    doc: TimelineDocument,
    *,
    asset_id: str,
    name: str,
    duration: float,
    has_video: bool,
    has_audio: bool,
    at: float | None = None,
    fps: float | None = None,
    width: int | None = None,
    height: int | None = None,
) -> list[Clip]:
    """Append a source asset to the end of the primary tracks (video + linked audio)."""
    start = doc.duration() if at is None else at
    created: list[Clip] = []
    video_clip: Clip | None = None
    if has_video:
        video_clip = Clip(
            kind="video",
            name=name,
            asset_id=asset_id,
            timeline_start=round(start, 6),
            duration=round(duration, 6),
            source_in=0.0,
            source_out=round(duration, 6),
            meta={"fps": fps, "width": width, "height": height},
        )
        doc.primary_video_track().clips.append(video_clip)
        created.append(video_clip)
    if has_audio:
        audio_clip = Clip(
            kind="audio",
            name=name,
            asset_id=asset_id,
            timeline_start=round(start, 6),
            duration=round(duration, 6),
            source_in=0.0,
            source_out=round(duration, 6),
            linked_clip_id=video_clip.id if video_clip else None,
        )
        doc.primary_audio_track().clips.append(audio_clip)
        created.append(audio_clip)
        if video_clip:
            video_clip.linked_clip_id = audio_clip.id
    if not doc.tracks_of_kind("video")[0].clips and not has_video and not has_audio:
        raise OperationError("asset has neither video nor audio")
    if width and height and not doc.primary_video_track().clips[:-1] and has_video:
        # First video clip defines the sequence format (unless reframed)
        if doc.settings.reframe is None:
            doc.settings.width, doc.settings.height = width, height
            doc.settings.aspect_ratio = _closest_aspect(width, height)
            if fps:
                doc.settings.fps = fps
    doc.sort()
    return created


def _closest_aspect(w: int, h: int) -> str:
    ratio = w / h
    options = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": 0.8, "4:3": 4 / 3}
    return min(options, key=lambda k: abs(options[k] - ratio))
