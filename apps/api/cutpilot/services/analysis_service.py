"""Transcript persistence/editing and analysis result access (async, API side)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cutpilot.core.errors import NotFoundError, ValidationFailed
from cutpilot.db.models import (
    AnalysisResult,
    MediaAsset,
    Project,
    Scene,
    Speaker,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)
from cutpilot.schemas.analysis import AnalysisResultOut, SceneOut, TranscriptOut

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


async def get_current_transcript(
    db: AsyncSession, project: Project, asset_id: uuid.UUID | None = None
) -> Transcript | None:
    q = (
        select(Transcript)
        .where(Transcript.project_id == project.id, Transcript.is_current.is_(True))
        .options(
            selectinload(Transcript.segments).selectinload(TranscriptSegment.words),
            selectinload(Transcript.speakers),
        )
    )
    if asset_id is not None:
        q = q.where(Transcript.asset_id == asset_id)
    return (await db.execute(q.order_by(Transcript.created_at.desc()))).scalars().first()


def serialize_transcript(t: Transcript) -> TranscriptOut:
    return TranscriptOut.model_validate(t)


async def list_transcripts(db: AsyncSession, project: Project) -> list[Transcript]:
    q = (
        select(Transcript)
        .where(Transcript.project_id == project.id, Transcript.is_current.is_(True))
        .options(
            selectinload(Transcript.segments).selectinload(TranscriptSegment.words),
            selectinload(Transcript.speakers),
        )
        .order_by(Transcript.created_at)
    )
    return list((await db.execute(q)).scalars().all())


async def update_segment_text(
    db: AsyncSession, project: Project, segment_id: uuid.UUID, text: str
) -> TranscriptSegment:
    seg = (
        await db.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.id == segment_id)
            .options(
                selectinload(TranscriptSegment.words), selectinload(TranscriptSegment.transcript)
            )
        )
    ).scalar_one_or_none()
    if seg is None or seg.transcript.project_id != project.id:
        raise NotFoundError("Segment not found")
    new_words = text.split()
    if not new_words:
        raise ValidationFailed("Segment text cannot be empty")
    seg.text = text.strip()
    old = sorted(seg.words, key=lambda w: w.index)
    if len(old) == len(new_words):
        for w, nt in zip(old, new_words, strict=True):
            w.text = nt
    else:
        # Word count changed: keep timing monotonic by distributing evenly across the segment span.
        for w in old:
            await db.delete(w)
        span = max(seg.end - seg.start, 0.1)
        step = span / len(new_words)
        for i, nt in enumerate(new_words):
            db.add(
                TranscriptWord(
                    segment_id=seg.id,
                    index=i,
                    start=round(seg.start + i * step, 3),
                    end=round(seg.start + (i + 1) * step, 3),
                    text=nt,
                    confidence=None,
                    speaker_id=seg.speaker_id,
                )
            )
    transcript = seg.transcript
    await db.flush()
    await _refresh_transcript_text(db, transcript)
    await db.commit()
    seg = (
        await db.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.id == seg.id)
            .options(selectinload(TranscriptSegment.words))
        )
    ).scalar_one()
    return seg


async def update_word(
    db: AsyncSession,
    project: Project,
    word_id: uuid.UUID,
    *,
    text: str | None,
    is_filler: bool | None,
) -> TranscriptWord:
    word = (
        await db.execute(
            select(TranscriptWord)
            .where(TranscriptWord.id == word_id)
            .options(
                selectinload(TranscriptWord.segment).selectinload(TranscriptSegment.transcript)
            )
        )
    ).scalar_one_or_none()
    if word is None or word.segment.transcript.project_id != project.id:
        raise NotFoundError("Word not found")
    if text is not None:
        word.text = text.strip() or word.text
        seg = word.segment
        words = sorted(
            (await db.execute(select(TranscriptWord).where(TranscriptWord.segment_id == seg.id)))
            .scalars()
            .all(),
            key=lambda w: w.index,
        )
        seg.text = " ".join(w.text if w.id != word.id else word.text for w in words)
        await _refresh_transcript_text(db, seg.transcript)
    if is_filler is not None:
        word.is_filler = is_filler
    await db.commit()
    await db.refresh(word)
    return word


async def _refresh_transcript_text(db: AsyncSession, transcript: Transcript) -> None:
    segs = (
        (
            await db.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id == transcript.id)
                .order_by(TranscriptSegment.index)
            )
        )
        .scalars()
        .all()
    )
    transcript.text = " ".join(s.text for s in segs)


async def rename_speaker(
    db: AsyncSession,
    project: Project,
    speaker_id: uuid.UUID,
    *,
    display_name: str,
    color: str | None,
) -> Speaker:
    spk = (
        await db.execute(
            select(Speaker)
            .where(Speaker.id == speaker_id)
            .options(selectinload(Speaker.transcript))
        )
    ).scalar_one_or_none()
    if spk is None or spk.transcript.project_id != project.id:
        raise NotFoundError("Speaker not found")
    spk.display_name = display_name.strip()
    if color:
        spk.color = color
    await db.commit()
    await db.refresh(spk)
    return spk


async def list_scenes(
    db: AsyncSession, project: Project, asset_id: uuid.UUID | None = None
) -> list[SceneOut]:
    q = select(Scene).where(Scene.project_id == project.id)
    if asset_id is not None:
        q = q.where(Scene.asset_id == asset_id)
    rows = (await db.execute(q.order_by(Scene.asset_id, Scene.index))).scalars().all()
    out = []
    for s in rows:
        item = SceneOut(
            id=s.id,
            asset_id=s.asset_id,
            index=s.index,
            start=s.start,
            end=s.end,
            thumbnail_url=f"/api/projects/{project.id}/scenes/{s.id}/thumbnail"
            if s.thumbnail_key
            else None,
            description=s.description,
            labels=s.labels,
        )
        out.append(item)
    return out


async def get_scene(db: AsyncSession, project: Project, scene_id: uuid.UUID) -> Scene:
    scene = await db.get(Scene, scene_id)
    if scene is None or scene.project_id != project.id:
        raise NotFoundError("Scene not found")
    return scene


async def list_results(
    db: AsyncSession,
    project: Project,
    *,
    kinds: list[str] | None = None,
    asset_id: uuid.UUID | None = None,
) -> list[AnalysisResultOut]:
    q = select(AnalysisResult).where(AnalysisResult.project_id == project.id)
    if kinds:
        q = q.where(AnalysisResult.kind.in_(kinds))
    if asset_id is not None:
        q = q.where(AnalysisResult.asset_id == asset_id)
    rows = (await db.execute(q.order_by(AnalysisResult.created_at.desc()))).scalars().all()
    # Keep only the newest result per (asset, kind)
    seen: set[tuple[uuid.UUID | None, str]] = set()
    out: list[AnalysisResultOut] = []
    for r in rows:
        key = (r.asset_id, r.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(AnalysisResultOut.model_validate(r))
    return out


async def primary_source_asset(
    db: AsyncSession, project: Project, asset_id: uuid.UUID | None = None
) -> MediaAsset:
    """The asset analysis applies to: explicit id, else the first ready original video/audio."""
    if asset_id is not None:
        asset = await db.get(MediaAsset, asset_id)
        if asset is None or asset.project_id != project.id:
            raise NotFoundError("Asset not found")
        return asset
    asset = (
        (
            await db.execute(
                select(MediaAsset)
                .where(
                    MediaAsset.project_id == project.id,
                    MediaAsset.kind == "original",
                    MediaAsset.status == "ready",
                    MediaAsset.media_type.in_(["video", "audio"]),
                )
                .order_by(MediaAsset.created_at)
            )
        )
        .scalars()
        .first()
    )
    if asset is None:
        raise ValidationFailed("Upload footage before running analysis")
    return asset


def transcript_context(project: Project) -> str:
    settings: dict[str, Any] = project.settings or {}
    return f"Project '{project.name}'. {project.description or ''} Target platform: {settings.get('target_platform', 'generic')}.".strip()
