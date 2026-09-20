"""Resolve reframe keyframes for a document from per-asset face tracks (computing tracks on demand)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cutpilot.db.models import AnalysisResult, MediaAsset, MediaMetadata
from cutpilot.media.reframe import timeline_reframe_keyframes, track_subject
from cutpilot.storage import get_storage
from cutpilot.timeline.model import TimelineDocument


def face_track_for_asset(
    session: Session, asset: MediaAsset, *, compute: bool = True
) -> dict[str, Any] | None:
    row = (
        session.execute(
            select(AnalysisResult)
            .where(AnalysisResult.asset_id == asset.id, AnalysisResult.kind == "face_track")
            .order_by(AnalysisResult.created_at.desc())
        )
        .scalars()
        .first()
    )
    if row is not None:
        return row.data
    if not compute or asset.media_type != "video":
        return None
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
    meta = session.execute(
        select(MediaMetadata).where(MediaMetadata.asset_id == asset.id)
    ).scalar_one_or_none()
    with get_storage().as_local_file(proxy.storage_key, suffix=".mp4") as path:
        data = track_subject(path, duration=float(meta.duration or 0.0) if meta else 0.0)
    session.add(
        AnalysisResult(
            project_id=asset.project_id,
            asset_id=asset.id,
            kind="face_track",
            content_hash=asset.content_hash,
            params_hash="yunet-v1",
            provider="opencv",
            model="yunet_2023mar",
            data=data,
        )
    )
    session.commit()
    return data


def ensure_reframe_keyframes(
    session: Session, doc: TimelineDocument, *, compute: bool = True
) -> TimelineDocument:
    """Fill settings.reframe.keyframes (timeline time) when the document asks for subject tracking."""
    rf = doc.settings.reframe
    if not rf or rf.get("mode") != "track" or rf.get("keyframes"):
        return doc
    tracks: dict[str, list[dict[str, float]]] = {}
    for asset_id in doc.asset_ids():
        asset = session.get(MediaAsset, uuid.UUID(asset_id))
        if asset is None or asset.media_type != "video":
            continue
        data = face_track_for_asset(session, asset, compute=compute)
        if data and data.get("coverage", 0) > 0:
            tracks[asset_id] = data["keyframes"]
    doc.settings.reframe = {
        **rf,
        "keyframes": timeline_reframe_keyframes(doc, tracks) if tracks else [],
        "tracked_assets": sorted(tracks),
    }
    return doc
