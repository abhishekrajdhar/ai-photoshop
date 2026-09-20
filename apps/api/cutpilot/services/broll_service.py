"""B-roll matching: resolve suggestion markers against the project's media library.

`BrollProvider` is the extension point; `LibraryBrollProvider` searches uploaded B-roll/images by
filename and (when available) vision descriptions. Stock-footage providers can implement the same
interface later.
"""

from __future__ import annotations

import abc
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cutpilot.db.models import AnalysisResult, MediaAsset, MediaMetadata

_TOKEN = re.compile(r"[a-z0-9]{3,}")
STOP = {"the", "and", "with", "for", "from", "footage", "video", "stock", "shot", "clip"}


def tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in STOP}


@dataclass
class BrollMatch:
    asset_id: uuid.UUID
    filename: str
    score: float
    duration: float | None
    media_type: str
    reason: str


class BrollProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    async def search(
        self, db: AsyncSession, project_id: uuid.UUID, query: str, *, limit: int = 5
    ) -> list[BrollMatch]: ...


class LibraryBrollProvider(BrollProvider):
    name = "library"

    async def search(
        self, db: AsyncSession, project_id: uuid.UUID, query: str, *, limit: int = 5
    ) -> list[BrollMatch]:
        q = tokens(query)
        if not q:
            return []
        assets = (
            (
                await db.execute(
                    select(MediaAsset).where(
                        MediaAsset.project_id == project_id,
                        MediaAsset.kind.in_(["broll", "image"]),
                        MediaAsset.status == "ready",
                    )
                )
            )
            .scalars()
            .all()
        )
        results: list[BrollMatch] = []
        for a in assets:
            name_tokens = tokens(a.filename)
            desc_tokens: set[str] = set()
            vision = (
                (
                    await db.execute(
                        select(AnalysisResult)
                        .where(AnalysisResult.asset_id == a.id, AnalysisResult.kind == "vision")
                        .order_by(AnalysisResult.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )
            if vision:
                for f in vision.data.get("frames", [])[:20]:
                    desc_tokens |= tokens(str(f.get("description", ""))) | tokens(
                        " ".join(f.get("objects", []))
                    )
            overlap_name = len(q & name_tokens)
            overlap_desc = len(q & desc_tokens)
            if overlap_name + overlap_desc == 0:
                continue
            score = (overlap_name * 1.0 + overlap_desc * 0.6) / len(q)
            meta = (
                await db.execute(select(MediaMetadata).where(MediaMetadata.asset_id == a.id))
            ).scalar_one_or_none()
            results.append(
                BrollMatch(
                    asset_id=a.id,
                    filename=a.filename,
                    score=round(min(1.0, score), 3),
                    duration=meta.duration if meta else None,
                    media_type=a.media_type,
                    reason=f"matched {', '.join(sorted(q & (name_tokens | desc_tokens)))}",
                )
            )
        return sorted(results, key=lambda r: -r.score)[:limit]


def get_broll_providers() -> list[BrollProvider]:
    return [LibraryBrollProvider()]
