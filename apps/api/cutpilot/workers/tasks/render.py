"""Render / export tasks (queue: render)."""

from __future__ import annotations

import contextlib
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cutpilot.core.config import get_settings
from cutpilot.core.errors import ValidationFailed
from cutpilot.core.logging import get_logger
from cutpilot.db.models import Export, MediaAsset, MediaMetadata, Project, Render, TimelineVersion
from cutpilot.media.ffmpeg import ffprobe, run_ffmpeg
from cutpilot.render.captions import caption_cues, to_ass, to_srt, to_vtt
from cutpilot.render.compiler import SourceMedia, compile_timeline
from cutpilot.render.exporters import to_edl, to_fcpxml, to_otio
from cutpilot.render.presets import ExportPreset
from cutpilot.services.events import sync_publisher
from cutpilot.services.job_service import JobContext
from cutpilot.storage import build_key, get_storage
from cutpilot.timeline.model import TimelineDocument
from cutpilot.workers.base import JobCancelled, job_task
from cutpilot.workers.celery_app import celery_app

log = get_logger(__name__)


def _work(job_id: uuid.UUID) -> Path:
    d = Path(get_settings().work_dir) / "jobs" / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


class _Sources:
    """Materialises the assets a document needs as local files (originals, never proxies)."""

    def __init__(self, session: Session, project_id: uuid.UUID, doc: TimelineDocument):
        self.session = session
        self.project_id = project_id
        self.doc = doc
        self.stack = contextlib.ExitStack()
        self.sources: dict[str, SourceMedia] = {}
        self.names: dict[str, str] = {}

    def __enter__(self) -> _Sources:
        storage = get_storage()
        from cutpilot.services.asset_service import resolve_storage_key

        for asset_id in sorted(self.doc.asset_ids()):
            asset = self.session.get(MediaAsset, uuid.UUID(asset_id))
            if asset is None or asset.project_id != self.project_id or asset.status != "ready":
                continue
            meta = self.session.execute(
                select(MediaMetadata).where(MediaMetadata.asset_id == asset.id)
            ).scalar_one_or_none()
            path = self.stack.enter_context(
                storage.as_local_file(
                    resolve_storage_key(asset), suffix=Path(asset.filename).suffix
                )
            )
            raw = (meta.raw if meta else {}) or {}
            self.sources[asset_id] = SourceMedia(
                asset_id=asset_id,
                path=Path(path),
                duration=float((meta.duration if meta else 0.0) or 0.0),
                width=meta.width if meta else None,
                height=meta.height if meta else None,
                has_video=bool(raw.get("has_video", asset.media_type == "video")),
                has_audio=bool(raw.get("has_audio", asset.media_type != "image")),
                is_image=asset.media_type == "image",
            )
            self.names[asset_id] = asset.filename
        return self

    def __exit__(self, *exc: object) -> None:
        self.stack.close()


def _store_output(
    session: Session,
    project_id: uuid.UUID,
    path: Path,
    *,
    kind: str,
    filename: str,
    mime: str,
    directory: str,
) -> MediaAsset:
    storage = get_storage()
    asset = MediaAsset(
        id=uuid.uuid4(),
        project_id=project_id,
        kind=kind,
        media_type="video"
        if mime.startswith("video")
        else ("audio" if mime.startswith("audio") else "text"),
        filename=filename,
        mime_type=mime,
        status="ready",
        storage_key="",
    )
    asset.storage_key = build_key(project_id, directory, f"{asset.id}{path.suffix}")
    size = path.stat().st_size
    info = None
    if mime.startswith("video"):
        info = ffprobe(path)
    storage.put_file(asset.storage_key, path, mime)
    asset.size_bytes = size
    session.add(asset)
    session.flush()
    if info is not None:
        w, h = info.display_size
        session.add(
            MediaMetadata(
                asset_id=asset.id,
                container=info.container,
                video_codec=info.video_codec,
                audio_codec=info.audio_codec,
                width=w,
                height=h,
                fps=info.fps,
                duration=info.duration,
                bitrate=info.bitrate,
                audio_channels=info.audio_channels,
                sample_rate=info.sample_rate,
                raw={"has_video": info.has_video, "has_audio": info.has_audio},
            )
        )
    session.commit()
    return asset


def _render_document(
    ctx: JobContext,
    session: Session,
    project: Project,
    doc: TimelineDocument,
    preset: ExportPreset,
    *,
    filename: str,
    kind: str,
    work: Path,
) -> tuple[MediaAsset, str, float]:
    from cutpilot.render.reframe_keys import ensure_reframe_keyframes

    ctx.progress(0.03, "Preparing")
    doc = ensure_reframe_keyframes(session, doc)
    with _Sources(session, project.id, doc) as src:
        missing = doc.asset_ids() - set(src.sources)
        if missing:
            log.warning("render_missing_assets", missing=sorted(missing))
        ctx.progress(0.05, "Compiling timeline")
        plan = compile_timeline(doc, src.sources, preset, work / "output.mp4", work / "compile")
        for w in plan.warnings:
            log.warning("render_warning", warning=w)
        ctx.progress(0.08, "Rendering")
        cmd = run_ffmpeg(
            plan.args,
            duration=plan.duration,
            on_progress=lambda f: ctx.progress(0.08 + 0.85 * f, "Rendering"),
            check_cancel=ctx.is_cancelled,
            timeout=6 * 3600,
        )
        if ctx.is_cancelled():
            raise JobCancelled()
        ctx.progress(0.95, "Storing output")
        asset = _store_output(
            session,
            project.id,
            plan.output,
            kind="render" if kind != "export" else "export",
            filename=filename,
            mime="video/mp4",
            directory="renders" if kind != "export" else "exports",
        )
        return asset, cmd, plan.duration


@celery_app.task(bind=True, name="cutpilot.workers.tasks.render.render_timeline", max_retries=1)
@job_task
def render_timeline(ctx: JobContext, session: Session, *, render_id: str) -> dict[str, Any]:
    render = session.get(Render, uuid.UUID(render_id))
    if render is None:
        raise ValidationFailed("Render not found")
    project = session.get(Project, render.project_id)
    version = session.get(TimelineVersion, render.timeline_version_id)
    assert project is not None and version is not None
    render.status = "RUNNING"
    session.commit()
    doc = TimelineDocument.model_validate(version.document)
    preset = ExportPreset(
        **{k: v for k, v in render.settings.items() if k in ExportPreset.__dataclass_fields__}
    )
    work = _work(ctx.id)
    try:
        asset, cmd, duration = _render_document(
            ctx,
            session,
            project,
            doc,
            preset,
            filename=str(render.settings.get("filename", "render.mp4")),
            kind=render.kind,
            work=work,
        )
        render.output_asset_id = asset.id
        render.ffmpeg_command = cmd
        render.duration = duration
        render.status = "COMPLETED"
        session.commit()
        sync_publisher.publish(
            "render.completed",
            {"render_id": str(render.id), "asset_id": str(asset.id)},
            project_id=project.id,
        )
        return {"render_id": str(render.id), "asset_id": str(asset.id), "duration": duration}
    except Exception as exc:
        session.rollback()
        render = session.get(Render, uuid.UUID(render_id))
        if render is not None:
            render.status = "FAILED"
            render.error = str(exc)[:4000]
            session.commit()
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


@celery_app.task(bind=True, name="cutpilot.workers.tasks.render.export_timeline", max_retries=1)
@job_task
def export_timeline(ctx: JobContext, session: Session, *, export_id: str) -> dict[str, Any]:
    export = session.get(Export, uuid.UUID(export_id))
    if export is None:
        raise ValidationFailed("Export not found")
    project = session.get(Project, export.project_id)
    version = (
        session.get(TimelineVersion, export.timeline_version_id)
        if export.timeline_version_id
        else None
    )
    assert project is not None and version is not None
    export.status = "RUNNING"
    session.commit()
    doc = TimelineDocument.model_validate(version.document)
    work = _work(ctx.id)
    try:
        fmt = export.format
        if fmt == "mp4":
            from cutpilot.render.presets import resolve_preset

            preset = resolve_preset(export.preset, export.settings)
            asset, cmd, duration = _render_document(
                ctx,
                session,
                project,
                doc,
                preset,
                filename=export.filename,
                kind="export",
                work=work,
            )
            render = Render(
                project_id=project.id,
                timeline_version_id=version.id,
                job_id=ctx.id,
                kind="final",
                status="COMPLETED",
                preset=export.preset,
                settings={**preset.to_dict(), "filename": export.filename},
                output_asset_id=asset.id,
                ffmpeg_command=cmd,
                duration=duration,
            )
            session.add(render)
            session.flush()
            export.render_id = render.id
        else:
            ctx.progress(0.2, f"Generating {fmt.upper()}")
            names = {
                str(a.id): a.filename
                for a in session.execute(
                    select(MediaAsset).where(MediaAsset.project_id == project.id)
                )
                .scalars()
                .all()
            }
            if fmt in ("srt", "vtt", "ass"):
                cues = caption_cues(doc)
                if not cues:
                    raise ValidationFailed(
                        "The timeline has no captions to export — add captions first"
                    )
                text = (
                    to_srt(cues)
                    if fmt == "srt"
                    else to_vtt(cues)
                    if fmt == "vtt"
                    else to_ass(
                        cues, doc.settings.caption_style, doc.settings.width, doc.settings.height
                    )
                )
                mime = "text/plain"
            elif fmt == "otio":
                text, mime = to_otio(doc, names), "application/json"
            elif fmt == "edl":
                text, mime = to_edl(doc, names), "text/plain"
            elif fmt == "fcpxml":
                text, mime = to_fcpxml(doc, names), "application/xml"
            else:
                raise ValidationFailed(f"Unsupported export format {fmt}")
            out = work / export.filename
            out.write_text(text, encoding="utf-8")
            asset = _store_output(
                session,
                project.id,
                out,
                kind="export",
                filename=export.filename,
                mime=mime,
                directory="exports",
            )
        export.output_asset_id = asset.id
        export.size_bytes = asset.size_bytes
        export.status = "COMPLETED"
        session.commit()
        sync_publisher.publish(
            "export.completed",
            {"export_id": str(export.id), "asset_id": str(asset.id), "format": fmt},
            project_id=project.id,
        )
        return {"export_id": str(export.id), "asset_id": str(asset.id), "format": fmt}
    except Exception as exc:
        session.rollback()
        export = session.get(Export, uuid.UUID(export_id))
        if export is not None:
            export.status = "FAILED"
            export.error = str(exc)[:4000]
            session.commit()
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
