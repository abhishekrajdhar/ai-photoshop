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


# ── Creator features ─────────────────────────────────────────────────────────


@celery_app.task(bind=True, name="cutpilot.workers.tasks.ai.detect_highlights_task", max_retries=0)
@job_task
def detect_highlights_task(
    ctx: JobContext,
    session: Session,
    *,
    asset_id: str,
    count: int = 5,
    min_len: float = 20.0,
    max_len: float = 60.0,
    platform: str | None = None,
) -> dict[str, Any]:
    from cutpilot.ai.highlight_analyzer import detect_highlights
    from cutpilot.ai.router import AIRouter
    from cutpilot.db.models import Highlight
    from cutpilot.services.timeline_sync import primary_timeline

    asset = session.get(MediaAsset, uuid.UUID(asset_id))
    if asset is None:
        raise ValidationFailed("Asset not found")
    project = session.get(Project, asset.project_id)
    assert project is not None
    timeline = primary_timeline(session, project.id)
    version = current_version(session, timeline) if timeline else None
    if version is None:
        raise ValidationFailed("Project has no timeline")
    pctx = load_context(session, project, asset, version)
    ctx.progress(0.1, "Finding highlights")
    router = AIRouter(session, project_id=project.id, user_id=ctx.job.user_id)
    items = detect_highlights(
        router, pctx, count=count, min_len=min_len, max_len=max_len, platform=platform
    )
    for old in (
        session.execute(
            select(Highlight).where(
                Highlight.project_id == project.id, Highlight.asset_id == asset.id
            )
        )
        .scalars()
        .all()
    ):
        session.delete(old)
    session.flush()
    provider = (router.session and None) or None
    for h in items:
        session.add(
            Highlight(
                project_id=project.id,
                asset_id=asset.id,
                start=h["start"],
                end=h["end"],
                title=h["title"],
                reason=h["reason"],
                caption_suggestion=h["caption_suggestion"],
                score=h["score"],
                factors={**h["factors"], "hook_line": h["hook_line"]},
                category=h["category"],
                provider=provider,
            )
        )
    session.commit()
    sync_publisher.publish(
        "highlight_detection.completed",
        {"asset_id": str(asset.id), "count": len(items)},
        project_id=project.id,
    )
    return {"count": len(items)}


def _find_phrase_time(
    words: list[dict[str, Any]], phrase: str, lo: float, hi: float
) -> tuple[float, float] | None:
    """Locate a spoken phrase inside [lo, hi] by matching normalised word sequences."""
    import re

    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).split()  # noqa: E731
    target = norm(phrase)
    if len(target) < 3:
        return None
    window = [w for w in words if lo <= w["start"] <= hi]
    toks = [norm(w["text"]) for w in window]
    flat = [(t[0], i) for i, t in enumerate(toks) if t]
    seq = [t for t, _ in flat]
    n = len(target)
    for i in range(len(seq) - n + 1):
        if seq[i : i + n] == target or (n >= 5 and seq[i : i + 4] == target[:4]):
            a, b = flat[i][1], flat[min(i + n - 1, len(flat) - 1)][1]
            return window[a]["start"], window[b]["end"]
    return None


@celery_app.task(bind=True, name="cutpilot.workers.tasks.ai.generate_shorts_task", max_retries=0)
@job_task
def generate_shorts_task(
    ctx: JobContext,
    session: Session,
    *,
    asset_id: str,
    count: int = 3,
    duration: int = 45,
    platform: str | None = None,
    highlight_ids: list[str] | None = None,
    caption_preset: str = "bold",
    reframe: bool = True,
) -> dict[str, Any]:
    """Create one 9:16 timeline per highlight: hook-first, jump cuts (silence/filler), captions, zooms, tracking."""
    from cutpilot.ai.expansion import current_transcript as _ct
    from cutpilot.ai.expansion import expand_operations, latest_result, transcript_words
    from cutpilot.ai.highlight_analyzer import detect_highlights
    from cutpilot.ai.router import AIRouter
    from cutpilot.db.models import Highlight, MediaMetadata
    from cutpilot.render.reframe_keys import ensure_reframe_keyframes
    from cutpilot.services.timeline_sync import create_timeline, primary_timeline
    from cutpilot.timeline.engine import add_source_clip, apply_operations
    from cutpilot.timeline.model import TimelineDocument, TimelineSettings
    from cutpilot.timeline.operations import EditOperation

    asset = session.get(MediaAsset, uuid.UUID(asset_id))
    if asset is None:
        raise ValidationFailed("Asset not found")
    project = session.get(Project, asset.project_id)
    assert project is not None
    meta = session.execute(
        select(MediaMetadata).where(MediaMetadata.asset_id == asset.id)
    ).scalar_one_or_none()
    if meta is None or not meta.duration:
        raise ValidationFailed("Asset metadata missing")
    timeline = primary_timeline(session, project.id)
    version = current_version(session, timeline) if timeline else None
    assert version is not None
    pctx = load_context(session, project, asset, version)

    # 1) highlights (existing, selected, or freshly detected)
    if highlight_ids:
        highlights = [
            h
            for h in session.execute(
                select(Highlight).where(Highlight.id.in_([uuid.UUID(h) for h in highlight_ids]))
            )
            .scalars()
            .all()
        ]
        items = [
            {
                "start": h.start,
                "end": h.end,
                "title": h.title,
                "caption_suggestion": h.caption_suggestion,
                "reason": h.reason,
                "factors": h.factors,
                "score": h.score,
                "hook_line": str(h.factors.get("hook_line", "")),
            }
            for h in highlights
        ]
    else:
        existing = list(
            session.execute(
                select(Highlight)
                .where(Highlight.project_id == project.id, Highlight.asset_id == asset.id)
                .order_by(Highlight.score.desc())
            )
            .scalars()
            .all()
        )
        if len(existing) >= count:
            items = [
                {
                    "start": h.start,
                    "end": h.end,
                    "title": h.title,
                    "caption_suggestion": h.caption_suggestion,
                    "reason": h.reason,
                    "factors": h.factors,
                    "score": h.score,
                    "hook_line": str(h.factors.get("hook_line", "")),
                }
                for h in existing[:count]
            ]
        else:
            ctx.progress(0.1, "Finding the strongest moments")
            router = AIRouter(session, project_id=project.id, user_id=ctx.job.user_id)
            items = detect_highlights(
                router,
                pctx,
                count=count,
                min_len=max(10.0, duration * 0.6),
                max_len=float(duration) * 1.4,
                platform=platform or "youtube_shorts",
            )
            for h in items:
                session.add(
                    Highlight(
                        project_id=project.id,
                        asset_id=asset.id,
                        start=h["start"],
                        end=h["end"],
                        title=h["title"],
                        reason=h["reason"],
                        caption_suggestion=h["caption_suggestion"],
                        score=h["score"],
                        factors={**h["factors"], "hook_line": h["hook_line"]},
                        category=h["category"],
                    )
                )
            session.commit()
    if not items:
        raise ValidationFailed("No highlights found to build Shorts from")

    transcript = _ct(session, project.id, asset.id)
    words = transcript_words(session, transcript) if transcript else []
    silence = latest_result(session, asset.id, "silence")
    filler = latest_result(session, asset.id, "filler")
    key_statements = sorted(
        (pctx.content or {}).get("aggregate", {}).get("key_statements", []),
        key=lambda k: -(k.get("importance") or 0),
    )
    created: list[dict[str, Any]] = []
    for i, h in enumerate(items[:count]):
        ctx.progress(0.2 + 0.7 * i / max(1, len(items)), f"Building Short {i + 1}")
        start, end = float(h["start"]), float(h["end"])
        # Trim to the requested duration at the last sentence end inside the window
        if end - start > duration:
            cutoff = start + duration
            ends = (
                [w["segment_end"] for w in words if start < w["segment_end"] <= cutoff]
                if words
                else []
            )
            end = max(ends) if ends and max(ends) > start + duration * 0.6 else cutoff
        settings = TimelineSettings(
            width=1080, height=1920, fps=meta.fps or 30.0, aspect_ratio="9:16"
        )
        doc = TimelineDocument.empty(
            timeline_id="pending", name=h["title"][:60] or f"Short {i + 1}", settings=settings
        )
        # Hook-first: if the hook line is spoken later in the window, put it first
        hook = _find_phrase_time(words, h.get("hook_line", ""), start, end) if words else None
        segments: list[tuple[float, float]] = []
        if hook and hook[0] > start + 2.0 and hook[1] - hook[0] >= 1.0:
            segments = [(hook[0], hook[1]), (start, hook[0]), (hook[1], end)]
        else:
            segments = [(start, end)]
        for s_in, s_out in segments:
            if s_out - s_in < 0.3:
                continue
            add_source_clip(
                doc,
                asset_id=str(asset.id),
                name=asset.filename,
                duration=s_out - s_in,
                has_video=asset.media_type == "video",
                has_audio=bool(meta.audio_codec),
                fps=meta.fps,
                width=meta.width,
                height=meta.height,
            )
            for track in doc.tracks:
                for c in track.clips:
                    if (
                        c.asset_id == str(asset.id)
                        and c.source_in == 0.0
                        and c.source_out == round(s_out - s_in, 6)
                    ):
                        c.source_in, c.source_out = round(s_in, 6), round(s_out, 6)
        doc.settings.width, doc.settings.height, doc.settings.aspect_ratio = 1080, 1920, "9:16"
        if reframe:
            doc.settings.reframe = {"mode": "track", "keyframes": []}
        # jump cuts from silence + filler inside the window
        ops: list[EditOperation] = []
        cuts = [
            c
            for c in (silence.data.get("suggested_cuts", []) if silence else [])
            if c["start"] >= start and c["end"] <= end
        ]
        if cuts:
            ops.append(
                EditOperation(
                    type="silence_removal",
                    asset_id=str(asset.id),
                    segments=[{"start": c["start"], "end": c["end"]} for c in cuts],
                    reason="Jump cuts (pauses)",
                    source="ai",
                    confidence=0.95,
                )
            )
        fills = [
            c
            for c in (filler.data.get("segments", []) if filler else [])
            if float(c["start"]) >= start and float(c["end"]) <= end
        ]
        if fills:
            ops.append(
                EditOperation(
                    type="filler_word_removal",
                    asset_id=str(asset.id),
                    segments=[{"start": float(c["start"]), "end": float(c["end"])} for c in fills],
                    reason="Jump cuts (fillers)",
                    source="ai",
                    confidence=0.9,
                )
            )
        # smart zooms at the most important statements inside the window (max one per 12 s)
        last_zoom = -1e9
        for k in key_statements:
            t = float(k["start"])
            if start <= t <= end - 2 and t - last_zoom >= 12 and (k.get("importance") or 0) >= 0.6:
                ops.append(
                    EditOperation(
                        type="zoom",
                        asset_id=str(asset.id),
                        timestamp=t,
                        duration=2.5,
                        scale=1.12,
                        reason=f"Emphasis: {str(k.get('text', ''))[:60]}",
                        source="ai",
                        confidence=0.7,
                    )
                )
                last_zoom = t
        if transcript:
            ops.append(
                EditOperation(
                    type="caption",
                    asset_id=str(asset.id),
                    params={"auto": True, "style": {"preset": caption_preset}},
                    reason="Captions",
                    source="ai",
                )
            )
        doc.settings.caption_style = doc.settings.caption_style.model_validate(
            {**doc.settings.caption_style.model_dump(), "preset": caption_preset}
        )
        expanded, _notes = expand_operations(
            session,
            project_id=project.id,
            asset_id=asset.id,
            operations=ops,
            caption_style=doc.settings.caption_style.model_dump(),
        )
        result = apply_operations(doc, expanded)
        final = ensure_reframe_keyframes(session, result.document) if reframe else result.document
        tl = create_timeline(
            session,
            project.id,
            name=doc.name,
            kind="short",
            document=final,
            label=f"Short from {h['title'][:40]}",
            source="ai",
        )
        tl.settings = {
            "highlight": {
                k: h.get(k)
                for k in (
                    "start",
                    "end",
                    "title",
                    "caption_suggestion",
                    "reason",
                    "score",
                    "factors",
                )
            },
            "platform": platform or "youtube_shorts",
            "target_duration": duration,
        }
        session.commit()
        created.append(
            {
                "timeline_id": str(tl.id),
                "name": tl.name,
                "duration": final.duration(),
                "title": h["title"],
                "caption_suggestion": h.get("caption_suggestion", ""),
            }
        )
    sync_publisher.publish(
        "short_generation.completed", {"timelines": created}, project_id=project.id
    )
    return {"timelines": created}


@celery_app.task(bind=True, name="cutpilot.workers.tasks.ai.generate_thumbnails", max_retries=0)
@job_task
def generate_thumbnails(
    ctx: JobContext, session: Session, *, asset_id: str, top: int = 6
) -> dict[str, Any]:
    import shutil
    from pathlib import Path

    from cutpilot.ai.expansion import latest_result
    from cutpilot.core.config import get_settings
    from cutpilot.db.models import AnalysisResult, MediaMetadata
    from cutpilot.media.proxy import extract_frames
    from cutpilot.media.thumbnails import candidate_times, score_frame
    from cutpilot.storage import build_key, get_storage

    asset = session.get(MediaAsset, uuid.UUID(asset_id))
    if asset is None or asset.media_type != "video":
        raise ValidationFailed("Thumbnails need a video asset")
    project = session.get(Project, asset.project_id)
    assert project is not None
    meta = session.execute(
        select(MediaMetadata).where(MediaMetadata.asset_id == asset.id)
    ).scalar_one_or_none()
    duration = float(meta.duration or 0.0) if meta else 0.0
    scenes = (latest_result(session, asset.id, "scenes") or AnalysisResult(data={})).data.get(
        "scenes", []
    )
    content = (latest_result(session, asset.id, "content") or AnalysisResult(data={})).data
    vision = (latest_result(session, asset.id, "vision") or AnalysisResult(data={})).data
    key_times = [
        float(k["start"]) for k in content.get("aggregate", {}).get("key_statements", [])[:10]
    ]
    key_times += [
        float(f["t"])
        for f in vision.get("frames", [])
        if float(f.get("thumbnail_candidate", 0)) >= 0.6
    ]
    times = candidate_times(duration, scenes, key_times)
    work = Path(get_settings().work_dir) / "jobs" / str(ctx.id)
    storage = get_storage()
    try:
        ctx.progress(0.1, f"Scoring {len(times)} candidate frames")
        proxy = (
            session.execute(
                select(MediaAsset).where(
                    MediaAsset.parent_asset_id == asset.id, MediaAsset.kind == "proxy"
                )
            )
            .scalars()
            .first()
            or asset
        )
        with storage.as_local_file(proxy.storage_key, suffix=".mp4") as video:
            frames = extract_frames(video, work / "cand", times, width=640)
            scored = []
            for t, f in zip(times, frames, strict=True):
                s = score_frame(f)
                scored.append({"time": t, **s})
            scored.sort(key=lambda x: -x["score"])
            best = scored[:top]
            ctx.progress(0.7, "Extracting full-resolution thumbnails")
        with storage.as_local_file(
            asset.storage_key, suffix=Path(asset.filename).suffix
        ) as original:
            full = extract_frames(original, work / "full", [b["time"] for b in best], width=1920)
        candidates = []
        for b, path in zip(best, full, strict=True):
            out = MediaAsset(
                id=uuid.uuid4(),
                project_id=project.id,
                parent_asset_id=asset.id,
                kind="thumbnail_candidate",
                media_type="image",
                filename=f"thumbnail_{b['time']:.1f}s.jpg",
                mime_type="image/jpeg",
                status="ready",
                storage_key="",
            )
            out.storage_key = build_key(project.id, "thumbnails", f"cand_{out.id}.jpg")
            storage.put_file(out.storage_key, path, "image/jpeg")
            out.size_bytes = storage.size(out.storage_key)
            out.extra = {"score": b["score"], "factors": b["factors"], "time": b["time"]}
            session.add(out)
            session.flush()
            candidates.append(
                {
                    "asset_id": str(out.id),
                    "time": b["time"],
                    "score": b["score"],
                    "factors": b["factors"],
                    "face": b.get("face"),
                }
            )
        session.add(
            AnalysisResult(
                project_id=project.id,
                asset_id=asset.id,
                kind="thumbnails",
                content_hash=asset.content_hash,
                params_hash="v1",
                provider="opencv",
                data={"candidates": candidates, "evaluated": len(scored)},
            )
        )
        session.commit()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    sync_publisher.publish(
        "thumbnail_generation.completed",
        {"asset_id": str(asset.id), "count": len(candidates)},
        project_id=project.id,
    )
    return {"candidates": len(candidates)}


@celery_app.task(bind=True, name="cutpilot.workers.tasks.ai.track_reframe", max_retries=0)
@job_task
def track_reframe(ctx: JobContext, session: Session, *, asset_id: str) -> dict[str, Any]:
    from cutpilot.render.reframe_keys import face_track_for_asset

    asset = session.get(MediaAsset, uuid.UUID(asset_id))
    if asset is None:
        raise ValidationFailed("Asset not found")
    ctx.progress(0.1, "Tracking subject")
    data = face_track_for_asset(session, asset, compute=True)
    sync_publisher.publish(
        "reframe_tracking.completed",
        {"asset_id": str(asset.id), "coverage": (data or {}).get("coverage")},
        project_id=asset.project_id,
    )
    return {
        "keyframes": len((data or {}).get("keyframes", [])),
        "coverage": (data or {}).get("coverage"),
    }
