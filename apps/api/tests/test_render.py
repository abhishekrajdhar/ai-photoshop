"""Render compiler + end-to-end render/export jobs (Celery eager)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient

from cutpilot.render.captions import Cue, to_srt, to_vtt
from cutpilot.render.compiler import SourceMedia, compile_timeline
from cutpilot.render.exporters import to_edl, to_fcpxml, to_otio
from cutpilot.render.presets import resolve_preset
from cutpilot.timeline.engine import add_source_clip, apply_operations
from cutpilot.timeline.model import TimelineDocument
from cutpilot.timeline.operations import EditOperation
from tests.media_fixtures import make_test_audio, make_test_video
from tests.test_media import _upload


def _probe(path: Path) -> dict:
    return json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )


def _spec_document() -> TimelineDocument:
    """The rendering test case from the spec: 60 s talking head with cuts, caption, zoom, music, 9:16."""
    doc = TimelineDocument.empty(timeline_id="t")
    add_source_clip(
        doc,
        asset_id="head",
        name="head",
        duration=60,
        has_video=True,
        has_audio=True,
        fps=30,
        width=1280,
        height=720,
    )
    ops = [
        EditOperation(type="remove_segment", asset_id="head", start=5, end=8),
        EditOperation(type="remove_segment", asset_id="head", start=17, end=20),
        EditOperation(
            type="caption",
            asset_id="head",
            start=21,
            end=25,
            text="Artificial intelligence is changing everything.",
            params={
                "words": [
                    {"text": "Artificial", "start": 0, "end": 0.8},
                    {"text": "intelligence", "start": 0.8, "end": 1.7},
                    {"text": "is", "start": 1.7, "end": 2.0},
                    {"text": "changing", "start": 2.0, "end": 2.8},
                    {"text": "everything.", "start": 2.8, "end": 4.0},
                ],
                "style": {"preset": "karaoke"},
            },
        ),
        EditOperation(type="zoom", asset_id="head", timestamp=30, duration=3, scale=1.1),
        EditOperation(
            type="music",
            asset_id="music",
            time_ref="timeline",
            timestamp=0,
            duration=54,
            params={"gain_db": -22, "loop": True, "source_duration": 20},
        ),
        EditOperation(
            type="reframe",
            params={
                "aspect_ratio": "9:16",
                "mode": "track",
                "keyframes": [{"t": 0, "x": 0.3}, {"t": 20, "x": 0.7}, {"t": 54, "x": 0.5}],
            },
        ),
    ]
    result = apply_operations(doc, ops)
    assert not result.rejected
    return result.document


def test_compiler_generates_expected_graph(tmp_path: Path) -> None:
    doc = _spec_document()
    sources = {
        "head": SourceMedia("head", tmp_path / "head.mp4", 60.0, 1280, 720),
        "music": SourceMedia("music", tmp_path / "music.mp3", 20.0, has_video=False),
    }
    plan = compile_timeline(
        doc, sources, resolve_preset("instagram_reel"), tmp_path / "out.mp4", tmp_path / "work"
    )
    graph = plan.filter_script.read_text()
    assert plan.duration == 54.0 and (plan.width, plan.height) == (1080, 1920)
    assert graph.count("]trim=start=") == 3  # three primary video segments
    assert "concat=n=3:v=1:a=0" in graph
    assert "sendcmd=f=" in graph and "crop@reframe=1080:1920" in graph
    assert "lerp(" in (tmp_path / "work" / "reframe_cmds.txt").read_text()
    assert "eval=frame" in graph  # zoom
    assert "-f concat" in " ".join(plan.args) and "cues.ffconcat" in " ".join(plan.args)  # captions
    assert (
        "sidechaincompress" in graph and "aloop=loop=-1" in graph and "volume=-22.0000dB" in graph
    )
    assert plan.args[-1].endswith("out.mp4") and "-t" in plan.args
    assert (
        len([p for p in plan.aux_files if p.suffix == ".png"]) >= 6
    )  # karaoke: 5 word states + blank


@pytest.mark.slow
def test_spec_render_case_produces_valid_mp4(tmp_path: Path) -> None:
    head = make_test_video(tmp_path / "head.mp4", duration=60, width=640, height=360, fps=30)
    music = make_test_audio(tmp_path / "music.wav", duration=20)
    doc = _spec_document()
    sources = {
        "head": SourceMedia("head", head, 60.0, 640, 360),
        "music": SourceMedia("music", music, 20.0, has_video=False),
    }
    preset = resolve_preset(
        "custom",
        {"width": 270, "height": 480, "fps": 30, "video_bitrate": "1M", "preset": "ultrafast"},
    )
    plan = compile_timeline(doc, sources, preset, tmp_path / "out.mp4", tmp_path / "work")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *plan.args],
        check=True,
        timeout=600,
    )
    info = _probe(plan.output)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["codec_name"]) == (270, 480, "h264")
    assert audio["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - 54.0) < 0.2


def test_caption_and_interchange_exports() -> None:
    doc = _spec_document()
    cues = [Cue(start=15.0, end=19.0, text="Hello world")]
    assert "00:00:15,000 --> 00:00:19,000" in to_srt(cues)
    assert to_vtt(cues).startswith("WEBVTT")
    names = {"head": "head.mp4", "music": "music.mp3"}
    otio_json = to_otio(doc, names)
    assert '"OTIO_SCHEMA": "Timeline.1"' in otio_json and "head.mp4" in otio_json
    edl = to_edl(doc, names)
    assert "TITLE: Main" in edl and edl.count("\n0") >= 3
    xml = to_fcpxml(doc, names)
    assert "<fcpxml" in xml and xml.count("<asset-clip") >= 3


async def test_render_and_export_jobs(auth_client: AsyncClient, tmp_path: Path) -> None:
    pid = (await auth_client.post("/api/projects", json={"name": "render"})).json()["id"]
    video = make_test_video(tmp_path / "talk.mp4", duration=3)
    await _upload(auth_client, pid, video)
    # add a caption so caption exports have content
    await auth_client.post(
        f"/api/projects/{pid}/timeline/operations",
        json={
            "operations": [
                {
                    "type": "caption",
                    "time_ref": "timeline",
                    "start": 0.5,
                    "end": 2.0,
                    "text": "hi there",
                }
            ]
        },
    )

    presets = (await auth_client.get("/api/render/presets")).json()
    assert any(p["id"] == "youtube_1080p" for p in presets)

    res = await auth_client.post(
        f"/api/projects/{pid}/render",
        json={
            "preset": "custom",
            "settings": {"width": 320, "height": 180, "preset": "ultrafast", "filename": "my cut"},
        },
    )
    assert res.status_code == 202, res.text
    render = (await auth_client.get(f"/api/projects/{pid}/renders/{res.json()['id']}")).json()
    assert render["status"] == "COMPLETED", render["error"]
    assert render["download_url"] and abs(render["duration"] - 3.0) < 0.2
    dl = await auth_client.get(render["download_url"])
    assert (
        dl.status_code == 200
        and dl.headers["content-disposition"].startswith("attachment")
        and "my_cut" in dl.headers["content-disposition"]
    ) or "my cut" in dl.headers["content-disposition"]

    for fmt in ("srt", "vtt", "otio", "edl", "fcpxml"):
        res = await auth_client.post(f"/api/projects/{pid}/exports", json={"format": fmt})
        assert res.status_code == 202, res.text
        exp = (await auth_client.get(f"/api/exports/{res.json()['id']}")).json()
        assert exp["status"] == "COMPLETED", (fmt, exp["error"])
        body = (await auth_client.get(exp["download_url"])).text
        assert body.strip(), fmt
    exports = (await auth_client.get(f"/api/projects/{pid}/exports")).json()
    assert len(exports) == 5

    # Renders appear as assets of kind "render"
    assets = (await auth_client.get(f"/api/projects/{pid}/assets")).json()
    assert any(a["kind"] == "render" for a in assets)
