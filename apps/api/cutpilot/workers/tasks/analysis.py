"""AI / analysis tasks (queue: ai). Transcription, audio, scenes, content, vision."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cutpilot.ai.diarization import assign_speakers, diarize
from cutpilot.ai.router import AIRouter
from cutpilot.ai.transcript_analyzer import analyze_transcript
from cutpilot.ai.transcription import get_transcription_provider
from cutpilot.ai.usage import log_usage
from cutpilot.ai.vision import VisionProvider
from cutpilot.analysis.filler import detect_fillers, filler_cut_segments
from cutpilot.core.config import get_settings
from cutpilot.core.constants import DEFAULT_FILLER_WORDS
from cutpilot.core.errors import ValidationFailed
from cutpilot.core.logging import get_logger
from cutpilot.db.models import (
    AnalysisResult,
    MediaAsset,
    MediaMetadata,
    Project,
    Scene,
    Speaker,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)
from cutpilot.media.proxy import extract_frames
from cutpilot.media.scenes import detect_scenes, sample_times_for_scenes
from cutpilot.media.silence import detect_silence, measure_loudness, suggest_silence_cuts
from cutpilot.services.events import sync_publisher
from cutpilot.services.job_service import JobContext
from cutpilot.storage import build_key, get_storage
from cutpilot.workers.base import JobCancelled, job_task
from cutpilot.workers.celery_app import celery_app

log = get_logger(__name__)
SPEAKER_COLORS = [
    "#7c5cff",
    "#2fd18a",
    "#f5b53f",
    "#4cc2ff",
    "#ff5c7a",
    "#a855f7",
    "#22c55e",
    "#f97316",
]


def _work(job_id: uuid.UUID) -> Path:
    d = Path(get_settings().work_dir) / "jobs" / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _asset(session: Session, asset_id: str) -> MediaAsset:
    asset = session.get(MediaAsset, uuid.UUID(asset_id))
    if asset is None:
        raise ValidationFailed("Asset not found")
    return asset


def _derived(session: Session, asset: MediaAsset, kind: str) -> MediaAsset | None:
    return (
        session.execute(
            select(MediaAsset).where(
                MediaAsset.parent_asset_id == asset.id, MediaAsset.kind == kind
            )
        )
        .scalars()
        .first()
    )


def _duration(session: Session, asset: MediaAsset) -> float:
    meta = session.execute(
        select(MediaMetadata).where(MediaMetadata.asset_id == asset.id)
    ).scalar_one_or_none()
    return float(meta.duration or 0.0) if meta else 0.0


def _params_hash(params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:32]


def _cached(
    session: Session, asset: MediaAsset, kind: str, params_hash: str
) -> AnalysisResult | None:
    if not asset.content_hash:
        return None
    return (
        session.execute(
            select(AnalysisResult)
            .where(
                AnalysisResult.kind == kind,
                AnalysisResult.content_hash == asset.content_hash,
                AnalysisResult.params_hash == params_hash,
            )
            .order_by(AnalysisResult.created_at.desc())
        )
        .scalars()
        .first()
    )


def _store_result(
    session: Session,
    project_id: uuid.UUID,
    asset: MediaAsset,
    kind: str,
    data: dict[str, Any],
    *,
    params_hash: str,
    provider: str | None = None,
    model: str | None = None,
) -> AnalysisResult:
    row = AnalysisResult(
        project_id=project_id,
        asset_id=asset.id,
        kind=kind,
        content_hash=asset.content_hash,
        params_hash=params_hash,
        provider=provider,
        model=model,
        data=data,
    )
    session.add(row)
    session.commit()
    sync_publisher.publish(
        "analysis.updated", {"kind": kind, "asset_id": str(asset.id)}, project_id=project_id
    )
    return row


def _current_transcript(
    session: Session, project_id: uuid.UUID, asset: MediaAsset
) -> Transcript | None:
    return (
        session.execute(
            select(Transcript)
            .where(
                Transcript.project_id == project_id,
                Transcript.asset_id == asset.id,
                Transcript.is_current.is_(True),
            )
            .order_by(Transcript.created_at.desc())
        )
        .scalars()
        .first()
    )


def _segments_payload(
    session: Session, transcript: Transcript
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    segs = (
        session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == transcript.id)
            .order_by(TranscriptSegment.index)
        )
        .scalars()
        .all()
    )
    speakers = {
        str(s.id): s.display_name
        for s in session.execute(select(Speaker).where(Speaker.transcript_id == transcript.id))
        .scalars()
        .all()
    }
    seg_out = [
        {
            "start": s.start,
            "end": s.end,
            "text": s.text,
            "speaker_id": str(s.speaker_id) if s.speaker_id else None,
        }
        for s in segs
    ]
    words: list[dict[str, Any]] = []
    for s in segs:
        for w in (
            session.execute(
                select(TranscriptWord)
                .where(TranscriptWord.segment_id == s.id)
                .order_by(TranscriptWord.index)
            )
            .scalars()
            .all()
        ):
            words.append({"id": str(w.id), "start": w.start, "end": w.end, "text": w.text})
    return seg_out, speakers, words


# ── Transcription ────────────────────────────────────────────────────────────


@celery_app.task(bind=True, name="cutpilot.workers.tasks.analysis.transcribe", max_retries=1)
@job_task
def transcribe(
    ctx: JobContext,
    session: Session,
    *,
    asset_id: str,
    language: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    asset = _asset(session, asset_id)
    project = session.get(Project, asset.project_id)
    assert project is not None
    audio = _derived(session, asset, "audio")
    if audio is None:
        raise ValidationFailed("Asset has no extracted audio track")

    provider = get_transcription_provider()
    # Cache: identical media already transcribed with the same provider (any of the owner's projects).
    if not force and asset.content_hash:
        existing = (
            session.execute(
                select(Transcript)
                .join(Project, Project.id == Transcript.project_id)
                .where(
                    Transcript.content_hash == asset.content_hash,
                    Transcript.provider == provider.name,
                    Project.owner_id == project.owner_id,
                )
                .order_by(Transcript.created_at.desc())
            )
            .scalars()
            .first()
        )
        if existing is not None:
            if existing.project_id == project.id and existing.asset_id == asset.id:
                ctx.progress(1.0, "Transcript already exists")
                _run_filler_detection(session, project, asset, existing)
                return {"transcript_id": str(existing.id), "cached": True}
            ctx.progress(0.2, "Reusing transcript from identical media")
            copied = _copy_transcript(session, existing, project.id, asset.id)
            _run_filler_detection(session, project, asset, copied)
            sync_publisher.publish(
                "transcription.completed",
                {"transcript_id": str(copied.id), "asset_id": str(asset.id), "cached": True},
                project_id=project.id,
            )
            return {"transcript_id": str(copied.id), "cached": True}

    ctx.progress(0.05, f"Transcribing with {provider.name}")
    storage = get_storage()
    with storage.as_local_file(audio.storage_key, suffix=".wav") as wav:
        result = provider.transcribe(
            wav,
            language=language,
            on_progress=lambda f: ctx.progress(0.05 + 0.7 * f, "Transcribing"),
        )
        if ctx.is_cancelled():
            raise JobCancelled()
        ctx.progress(0.78, "Identifying speakers")
        turns = diarize(wav)
    labels = assign_speakers(result.segments, turns)
    log_usage(
        session,
        provider=result.provider,
        model=result.model,
        operation="transcription",
        project_id=project.id,
        user_id=ctx.job.user_id,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
        meta={"segments": len(result.segments), "diarized": turns is not None},
    )

    ctx.progress(0.85, "Saving transcript")
    for old in (
        session.execute(
            select(Transcript).where(
                Transcript.project_id == project.id, Transcript.asset_id == asset.id
            )
        )
        .scalars()
        .all()
    ):
        old.is_current = False
    transcript = Transcript(
        project_id=project.id,
        asset_id=asset.id,
        provider=result.provider,
        model=result.model,
        language=result.language,
        text=result.text,
        confidence=result.confidence(),
        content_hash=asset.content_hash,
        is_current=True,
    )
    session.add(transcript)
    session.flush()
    speakers: dict[str, Speaker] = {}
    for i, label in enumerate(labels):
        spk = Speaker(
            transcript_id=transcript.id,
            label=label,
            display_name=f"Speaker {i + 1}",
            color=SPEAKER_COLORS[i % len(SPEAKER_COLORS)],
        )
        session.add(spk)
        speakers[label] = spk
    session.flush()
    for si, seg in enumerate(result.segments):
        row = TranscriptSegment(
            transcript_id=transcript.id,
            index=si,
            start=seg.start,
            end=seg.end,
            text=seg.text,
            confidence=seg.confidence,
            speaker_id=speakers[seg.speaker].id if seg.speaker in speakers else None,
        )
        session.add(row)
        session.flush()
        for wi, w in enumerate(seg.words):
            session.add(
                TranscriptWord(
                    segment_id=row.id,
                    index=wi,
                    start=w.start,
                    end=w.end,
                    text=w.text,
                    confidence=w.confidence,
                    speaker_id=speakers[w.speaker].id if w.speaker in speakers else None,
                )
            )
    session.commit()
    _run_filler_detection(session, project, asset, transcript)
    sync_publisher.publish(
        "transcription.completed",
        {"transcript_id": str(transcript.id), "asset_id": str(asset.id)},
        project_id=project.id,
    )
    return {
        "transcript_id": str(transcript.id),
        "segments": len(result.segments),
        "language": result.language,
    }


def _copy_transcript(
    session: Session, src: Transcript, project_id: uuid.UUID, asset_id: uuid.UUID
) -> Transcript:
    for old in (
        session.execute(
            select(Transcript).where(
                Transcript.project_id == project_id, Transcript.asset_id == asset_id
            )
        )
        .scalars()
        .all()
    ):
        old.is_current = False
    t = Transcript(
        project_id=project_id,
        asset_id=asset_id,
        provider=src.provider,
        model=src.model,
        language=src.language,
        text=src.text,
        confidence=src.confidence,
        content_hash=src.content_hash,
        is_current=True,
    )
    session.add(t)
    session.flush()
    spk_map: dict[uuid.UUID, uuid.UUID] = {}
    for s in (
        session.execute(select(Speaker).where(Speaker.transcript_id == src.id)).scalars().all()
    ):
        n = Speaker(transcript_id=t.id, label=s.label, display_name=s.display_name, color=s.color)
        session.add(n)
        session.flush()
        spk_map[s.id] = n.id
    for seg in (
        session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == src.id)
            .order_by(TranscriptSegment.index)
        )
        .scalars()
        .all()
    ):
        ns = TranscriptSegment(
            transcript_id=t.id,
            index=seg.index,
            start=seg.start,
            end=seg.end,
            text=seg.text,
            confidence=seg.confidence,
            speaker_id=spk_map.get(seg.speaker_id) if seg.speaker_id else None,
        )
        session.add(ns)
        session.flush()
        for w in (
            session.execute(
                select(TranscriptWord)
                .where(TranscriptWord.segment_id == seg.id)
                .order_by(TranscriptWord.index)
            )
            .scalars()
            .all()
        ):
            session.add(
                TranscriptWord(
                    segment_id=ns.id,
                    index=w.index,
                    start=w.start,
                    end=w.end,
                    text=w.text,
                    confidence=w.confidence,
                    speaker_id=spk_map.get(w.speaker_id) if w.speaker_id else None,
                    is_filler=w.is_filler,
                )
            )
    session.commit()
    return t


def _run_filler_detection(
    session: Session, project: Project, asset: MediaAsset, transcript: Transcript
) -> AnalysisResult:
    words_rows: list[TranscriptWord] = []
    for seg in (
        session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == transcript.id)
            .order_by(TranscriptSegment.index)
        )
        .scalars()
        .all()
    ):
        words_rows.extend(
            session.execute(
                select(TranscriptWord)
                .where(TranscriptWord.segment_id == seg.id)
                .order_by(TranscriptWord.index)
            )
            .scalars()
            .all()
        )
    filler_list = (project.settings or {}).get("filler_words") or list(DEFAULT_FILLER_WORDS)
    hits = detect_fillers(
        [{"start": w.start, "end": w.end, "text": w.text} for w in words_rows], filler_list
    )
    for w in words_rows:
        w.is_filler = False
    for h in hits:
        for idx in h.word_indices:
            words_rows[idx].is_filler = True
    session.commit()
    segments = filler_cut_segments(hits)
    data = {
        "count": len(hits),
        "filler_words": filler_list,
        "hits": [{"start": h.start, "end": h.end, "text": h.text} for h in hits],
        "segments": segments,
        "removable_seconds": round(sum(float(s["end"]) - float(s["start"]) for s in segments), 3),
    }
    return _store_result(
        session,
        project.id,
        asset,
        "filler",
        data,
        params_hash=_params_hash({"filler_words": filler_list, "transcript": str(transcript.id)}),
    )


# ── Audio analysis (silence + loudness) ──────────────────────────────────────


@celery_app.task(bind=True, name="cutpilot.workers.tasks.analysis.audio_analysis", max_retries=1)
@job_task
def audio_analysis(
    ctx: JobContext, session: Session, *, asset_id: str, force: bool = False
) -> dict[str, Any]:
    asset = _asset(session, asset_id)
    project = session.get(Project, asset.project_id)
    assert project is not None
    audio = _derived(session, asset, "audio")
    if audio is None:
        raise ValidationFailed("Asset has no extracted audio track")
    settings = project.settings or {}
    params = {
        "threshold_db": float(settings.get("silence_threshold_db", -35.0)),
        "min_duration": float(settings.get("silence_min_duration", 0.8)),
    }
    ph = _params_hash(params)
    if not force:
        cached = _cached(session, asset, "silence", ph)
        if cached is not None and cached.project_id == project.id:
            ctx.progress(1.0, "Using cached audio analysis")
            return {"cached": True, "silences": len(cached.data.get("segments", []))}
    duration = _duration(session, asset)
    storage = get_storage()
    with storage.as_local_file(audio.storage_key, suffix=".wav") as wav:
        ctx.progress(0.2, "Detecting silence")
        silences = detect_silence(
            wav,
            threshold_db=params["threshold_db"],
            min_duration=params["min_duration"],
            total_duration=duration,
        )
        ctx.progress(0.6, "Measuring loudness")
        loudness = measure_loudness(wav)
    cuts = suggest_silence_cuts(silences)
    data = {
        "params": params,
        "segments": silences,
        "suggested_cuts": cuts,
        "count": len(silences),
        "total_silence_seconds": round(sum(s["duration"] for s in silences), 3),
        "removable_seconds": round(sum(c["duration"] for c in cuts), 3),
    }
    _store_result(session, project.id, asset, "silence", data, params_hash=ph)
    _store_result(
        session,
        project.id,
        asset,
        "audio_stats",
        {
            **loudness,
            "needs_normalization": loudness.get("integrated_lufs", -16) < -20
            or loudness.get("integrated_lufs", -16) > -12,
        },
        params_hash="v1",
    )
    return {
        "silences": len(silences),
        "removable_seconds": data["removable_seconds"],
        "loudness": loudness,
    }


# ── Scene detection ──────────────────────────────────────────────────────────


@celery_app.task(bind=True, name="cutpilot.workers.tasks.analysis.scene_detection", max_retries=1)
@job_task
def scene_detection(
    ctx: JobContext, session: Session, *, asset_id: str, force: bool = False
) -> dict[str, Any]:
    asset = _asset(session, asset_id)
    project = session.get(Project, asset.project_id)
    assert project is not None
    if asset.media_type != "video":
        raise ValidationFailed("Scene detection requires a video asset")
    params = {"threshold": 27.0, "min_scene_len": 1.0}
    ph = _params_hash(params)
    if not force:
        cached = _cached(session, asset, "scenes", ph)
        if cached is not None and cached.project_id == project.id:
            ctx.progress(1.0, "Using cached scenes")
            return {"cached": True, "scenes": cached.data.get("count", 0)}
    source = _derived(session, asset, "proxy") or asset
    duration = _duration(session, asset)
    storage = get_storage()
    work = _work(ctx.id)
    try:
        with storage.as_local_file(source.storage_key, suffix=".mp4") as video:
            ctx.progress(0.1, "Detecting shot boundaries")
            scenes = detect_scenes(
                video,
                threshold=params["threshold"],
                min_scene_len_seconds=params["min_scene_len"],
                duration=duration,
            )
            ctx.progress(0.6, f"Found {len(scenes)} scenes, extracting thumbnails")
            for old in (
                session.execute(select(Scene).where(Scene.asset_id == asset.id)).scalars().all()
            ):
                session.delete(old)
            session.flush()
            mids = [s["start"] + (s["end"] - s["start"]) / 2 for s in scenes]
            frames = extract_frames(video, work / "scenes", mids, width=480)
            for s, frame in zip(scenes, frames, strict=False):
                key = build_key(project.id, "thumbnails", f"scene_{asset.id}_{s['index']:04d}.jpg")
                storage.put_file(key, frame, "image/jpeg")
                session.add(
                    Scene(
                        project_id=project.id,
                        asset_id=asset.id,
                        index=s["index"],
                        start=s["start"],
                        end=s["end"],
                        thumbnail_key=key,
                    )
                )
            session.commit()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    data = {"params": params, "count": len(scenes), "scenes": scenes}
    _store_result(session, project.id, asset, "scenes", data, params_hash=ph)
    return {"scenes": len(scenes)}


# ── Content (transcript) analysis ────────────────────────────────────────────


@celery_app.task(bind=True, name="cutpilot.workers.tasks.analysis.content_analysis", max_retries=1)
@job_task
def content_analysis(
    ctx: JobContext, session: Session, *, asset_id: str, force: bool = False
) -> dict[str, Any]:
    asset = _asset(session, asset_id)
    project = session.get(Project, asset.project_id)
    assert project is not None
    transcript = _current_transcript(session, project.id, asset)
    if transcript is None:
        raise ValidationFailed("Transcribe the footage before content analysis")
    from cutpilot.services.analysis_service import transcript_context

    context = transcript_context(project)
    ph = _params_hash(
        {
            "transcript": str(transcript.id),
            "text_hash": hashlib.sha256(transcript.text.encode()).hexdigest()[:16],
            "context": context,
        }
    )
    if not force:
        cached = _cached(session, asset, "content", ph)
        if cached is not None and cached.project_id == project.id:
            ctx.progress(1.0, "Using cached content analysis")
            return {"cached": True}
    segments, speakers, _ = _segments_payload(session, transcript)
    if not segments:
        raise ValidationFailed("Transcript is empty")
    router = AIRouter(session, project_id=project.id, user_id=ctx.job.user_id)
    ctx.progress(0.05, "Analysing transcript")
    data = analyze_transcript(
        router,
        segments,
        context=context,
        duration=_duration(session, asset) or segments[-1]["end"],
        speakers=speakers,
        on_progress=lambda f: ctx.progress(f, "Analysing transcript"),
    )
    from cutpilot.ai.router import available_providers

    _store_result(
        session,
        project.id,
        asset,
        "content",
        data,
        params_hash=ph,
        provider=(available_providers() or [None])[0],
    )
    return {
        "topics": data["summary"].get("topics", [])[:8],
        "chapters": len(data["summary"].get("chapters", [])),
    }


# ── Vision analysis ──────────────────────────────────────────────────────────


@celery_app.task(bind=True, name="cutpilot.workers.tasks.analysis.vision_analysis", max_retries=1)
@job_task
def vision_analysis(
    ctx: JobContext, session: Session, *, asset_id: str, force: bool = False, max_frames: int = 48
) -> dict[str, Any]:
    asset = _asset(session, asset_id)
    project = session.get(Project, asset.project_id)
    assert project is not None
    if asset.media_type != "video":
        raise ValidationFailed("Vision analysis requires a video asset")
    params = {"max_frames": max_frames, "v": 1}
    ph = _params_hash(params)
    if not force:
        cached = _cached(session, asset, "vision", ph)
        if cached is not None and cached.project_id == project.id:
            ctx.progress(1.0, "Using cached vision analysis")
            return {"cached": True, "frames": len(cached.data.get("frames", []))}
    scenes_row = (
        session.execute(
            select(AnalysisResult)
            .where(AnalysisResult.asset_id == asset.id, AnalysisResult.kind == "scenes")
            .order_by(AnalysisResult.created_at.desc())
        )
        .scalars()
        .first()
    )
    duration = _duration(session, asset)
    scenes = (
        scenes_row.data.get("scenes", [])
        if scenes_row
        else [{"index": 0, "start": 0.0, "end": duration}]
    )
    times = sample_times_for_scenes(scenes, max_frames=max_frames)
    if not times:
        raise ValidationFailed("No frames to sample")
    source = _derived(session, asset, "proxy") or asset
    storage = get_storage()
    work = _work(ctx.id)
    from cutpilot.services.analysis_service import transcript_context

    try:
        with storage.as_local_file(source.storage_key, suffix=".mp4") as video:
            ctx.progress(0.1, f"Sampling {len(times)} frames")
            frames = extract_frames(video, work / "frames", times, width=640)
        router = AIRouter(session, project_id=project.id, user_id=ctx.job.user_id)
        vision = VisionProvider(router, context=transcript_context(project))
        ctx.progress(0.3, "Analysing frames")
        data = vision.analyze_frames(
            list(zip(times, frames, strict=True)),
            on_progress=lambda f: ctx.progress(f, "Analysing frames"),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # Attach descriptions to stored scenes
    scene_rows = (
        session.execute(select(Scene).where(Scene.asset_id == asset.id).order_by(Scene.index))
        .scalars()
        .all()
    )
    for s in scene_rows:
        inside = [f for f in data["frames"] if s.start <= f["t"] < s.end]
        if inside:
            s.description = "; ".join(f["description"] for f in inside[:2])[:1000]
            s.labels = {
                "shot_types": sorted({f["shot_type"] for f in inside}),
                "people": max(f["people_count"] for f in inside),
                "environment": inside[0]["environment"],
            }
    session.commit()
    data["params"] = params
    data["sampled_times"] = times
    from cutpilot.ai.router import available_providers

    _store_result(
        session,
        project.id,
        asset,
        "vision",
        data,
        params_hash=ph,
        provider=(available_providers() or [None])[0],
    )
    return {"frames": len(data["frames"]), "opportunities": len(data["editing_opportunities"])}
