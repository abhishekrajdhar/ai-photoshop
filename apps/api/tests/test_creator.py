"""Highlights, Shorts generation, thumbnails, B-roll matching, multicam sync, sequence settings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from httpx import AsyncClient

from cutpilot.analysis.audio_sync import estimate_offset
from cutpilot.media.reframe import timeline_reframe_keyframes
from cutpilot.timeline.engine import add_source_clip
from cutpilot.timeline.model import TimelineDocument
from tests.fakes import DEFAULT_RESPONSES, FakeTranscription, ScriptedLLM
from tests.media_fixtures import make_speech_like_audio, make_test_image, make_test_video
from tests.test_media import _upload

HIGHLIGHTS_JSON = {
    "highlights": [
        {
            "start": 0.5,
            "end": 7.0,
            "title": "Hello world moment",
            "caption_suggestion": "Testing!",
            "reason": "opening hook",
            "category": "hook",
            "factors": {
                "informative": 0.6,
                "surprising": 0.3,
                "funny": 0.1,
                "emotional": 0.2,
                "hook_strength": 0.9,
                "clarity": 0.8,
                "self_contained": 0.7,
            },
            "hook_line": "Basically we are testing the pipeline",
        },
        {
            "start": 7.5,
            "end": 11.5,
            "title": "Second moment",
            "caption_suggestion": "",
            "reason": "clear",
            "category": "informative",
            "factors": {"informative": 0.9, "clarity": 0.9},
            "hook_line": "",
        },
    ]
}


def _install(monkeypatch: pytest.MonkeyPatch, llm: ScriptedLLM) -> None:
    from cutpilot.ai import router, transcription
    from cutpilot.workers.tasks import analysis as tasks

    monkeypatch.setattr(router, "available_providers", lambda: ["openai"])
    monkeypatch.setattr(router, "_provider", lambda name: llm)
    monkeypatch.setattr(transcription, "get_transcription_provider", lambda: FakeTranscription())
    monkeypatch.setattr(tasks, "get_transcription_provider", lambda: FakeTranscription())


async def test_highlights_shorts_and_thumbnails(
    auth_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = ScriptedLLM(
        [
            {"json": DEFAULT_RESPONSES["SectionAnalysis"]},
            {"json": DEFAULT_RESPONSES["ProjectSummary"]},
            {"json": HIGHLIGHTS_JSON},
        ]
    )
    _install(monkeypatch, llm)
    pid = (await auth_client.post("/api/projects", json={"name": "creator"})).json()["id"]
    video = make_test_video(tmp_path / "talk.mp4", duration=12)
    asset = (await _upload(auth_client, pid, video))["asset"]
    await auth_client.post(
        f"/api/projects/{pid}/analyze",
        json={"steps": ["transcription", "audio", "scenes", "content"]},
    )

    res = await auth_client.post(
        f"/api/projects/{pid}/highlights", json={"count": 3, "min_seconds": 5, "max_seconds": 20}
    )
    assert res.status_code == 200, res.text
    hl = (await auth_client.get(f"/api/projects/{pid}/highlights")).json()
    assert len(hl) == 2 and hl[0]["score"] > hl[1]["score"]
    assert set(hl[0]["factors"]) >= {"informative", "hook_strength", "clarity", "hook_line"}

    res = await auth_client.post(
        f"/api/projects/{pid}/shorts",
        json={
            "count": 2,
            "duration": 15,
            "caption_preset": "bold",
            "platform": "instagram_reels",
            "auto_render": True,
            "render_preset": "preview",
        },
    )
    assert res.status_code == 200, res.text
    job = (await auth_client.get(f"/api/jobs/{res.json()['jobs'][0]['id']}")).json()
    assert job["status"] == "COMPLETED", job["error"]
    created = job["result"]["timelines"]
    assert all(c.get("render_id") for c in created)
    renders = (await auth_client.get(f"/api/projects/{pid}/renders")).json()
    assert len([r for r in renders if r["status"] == "COMPLETED"]) == 2 and all(
        r["settings"]["width"] == 1280 for r in renders
    )
    timelines = (await auth_client.get(f"/api/projects/{pid}/timelines")).json()
    shorts = [t for t in timelines if t["kind"] == "short"]
    assert len(shorts) == 2
    state = (
        await auth_client.get(
            f"/api/projects/{pid}/timeline", params={"timeline_id": shorts[0]["id"]}
        )
    ).json()
    doc = state["document"]
    assert (
        doc["settings"]["width"] == 1080
        and doc["settings"]["height"] == 1920
        and doc["settings"]["reframe"]["mode"] == "track"
    )
    video_clips = doc["tracks"][0]["clips"]
    assert len(video_clips) >= 2  # hook-first reordering produced multiple clips
    assert video_clips[0]["source_in"] > 0.5  # the hook sentence was moved to the front
    caption_clips = next(t for t in doc["tracks"] if t["kind"] == "caption")["clips"]
    assert caption_clips and doc["settings"]["caption_style"]["preset"] == "bold"
    assert shorts[0]["settings"]["highlight"]["title"] == "Hello world moment"

    # Thumbnails
    res = await auth_client.post(f"/api/projects/{pid}/thumbnails")
    job = (await auth_client.get(f"/api/jobs/{res.json()['jobs'][0]['id']}")).json()
    assert job["status"] == "COMPLETED", job["error"]
    thumbs = (await auth_client.get(f"/api/projects/{pid}/thumbnails")).json()
    assert thumbs["source_asset_id"] == asset["id"] and 1 <= len(thumbs["candidates"]) <= 6
    c = thumbs["candidates"][0]
    assert {"sharpness", "exposure", "face_visibility", "text_safe_area"} <= set(c["factors"])
    assert (await auth_client.get(c["url"])).headers["content-type"] == "image/jpeg"

    # Reframe tracking job runs and stores a track (no faces in a test pattern → centre)
    res = await auth_client.post(f"/api/projects/{pid}/reframe/track")
    job = (await auth_client.get(f"/api/jobs/{res.json()['jobs'][0]['id']}")).json()
    assert job["status"] == "COMPLETED", job["error"]
    assert job["result"]["coverage"] == 0.0


async def test_broll_library_matching_and_placement(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    pid = (await auth_client.post("/api/projects", json={"name": "broll"})).json()["id"]
    video = make_test_video(tmp_path / "talk.mp4", duration=6)
    await _upload(auth_client, pid, video)
    img = make_test_image(tmp_path / "data-center-servers.png")
    b = (await _upload(auth_client, pid, img, mime="image/png"))["asset"]
    await auth_client.patch(f"/api/assets/{b['id']}", json={"kind": "image"})
    # A B-roll suggestion without media becomes a marker
    await auth_client.post(
        f"/api/projects/{pid}/timeline/operations",
        json={
            "operations": [
                {
                    "type": "insert_broll",
                    "time_ref": "timeline",
                    "timestamp": 1.0,
                    "duration": 2.5,
                    "query": "AI data center servers",
                },
                {
                    "type": "insert_broll",
                    "time_ref": "timeline",
                    "timestamp": 4.0,
                    "duration": 2,
                    "query": "ocean waves",
                },
            ]
        },
    )
    state = (await auth_client.get(f"/api/projects/{pid}/timeline")).json()
    assert len([m for m in state["document"]["markers"] if m["kind"] == "broll_suggestion"]) == 2

    res = await auth_client.get(f"/api/projects/{pid}/broll/search", params={"q": "data center"})
    assert res.json() and res.json()[0]["filename"].startswith("data-center")

    res = await auth_client.post(f"/api/projects/{pid}/broll/resolve")
    body = res.json()
    assert len(body["placed"]) == 1 and len(body["unresolved"]) == 1
    state = (await auth_client.get(f"/api/projects/{pid}/timeline")).json()
    v2 = state["document"]["tracks"][1]["clips"]
    assert (
        len(v2) == 1
        and v2[0]["kind"] == "image"
        and v2[0]["timeline_start"] == 1.0
        and v2[0]["duration"] == 2.5
    )
    assert len(state["document"]["markers"]) == 1


def test_waveform_offset_estimation(tmp_path: Path) -> None:
    pattern = [
        (0.4, True),
        (0.6, False),
        (0.3, True),
        (0.9, False),
        (0.5, True),
        (0.4, False),
        (0.2, True),
        (1.2, False),
        (0.7, True),
    ]
    ref = make_speech_like_audio(tmp_path / "ref.wav", pattern=pattern)
    other = make_speech_like_audio(
        tmp_path / "other.wav", pattern=[(1.5, False), *pattern]
    )  # starts 1.5 s later
    res = estimate_offset(ref, other)
    assert abs(res["offset"] - (-1.5)) < 0.05 or abs(res["offset"] - 1.5) < 0.05
    assert res["confidence"] > 0.2


def test_timeline_reframe_keyframes_follow_cuts() -> None:
    doc = TimelineDocument.empty(timeline_id="t")
    add_source_clip(doc, asset_id="a", name="a", duration=10, has_video=True, has_audio=False)
    clip = doc.primary_video_track().clips[0]
    clip.source_in, clip.source_out, clip.duration = 4.0, 8.0, 4.0
    keys = timeline_reframe_keyframes(
        doc, {"a": [{"t": 0, "x": 0.2, "y": 0.5}, {"t": 10, "x": 0.8, "y": 0.5}]}, step=1.0
    )
    assert keys[0]["t"] == 0.0 and abs(keys[0]["x"] - 0.44) < 0.01  # source 4 s → 0.2 + 0.4*0.6
    assert keys[-1]["t"] == 4.0 and abs(keys[-1]["x"] - 0.68) < 0.01


async def test_sequence_settings_update(auth_client: AsyncClient, tmp_path: Path) -> None:
    pid = (await auth_client.post("/api/projects", json={"name": "seq"})).json()["id"]
    await _upload(auth_client, pid, make_test_video(tmp_path / "talk.mp4", duration=3))
    res = await auth_client.patch(
        f"/api/projects/{pid}/sequence",
        json={
            "caption_style": {"preset": "karaoke"},
            "audio": {"normalize_audio": True},
            "aspect_ratio": "9:16",
            "reframe_mode": "track",
        },
    )
    assert res.status_code == 200, res.text
    doc = res.json()["document"]
    assert (
        doc["settings"]["caption_style"]["preset"] == "karaoke"
        and doc["settings"]["caption_style"]["animation"] == "karaoke"
    )
    assert doc["settings"]["audio"]["normalize_audio"] is True
    assert (doc["settings"]["width"], doc["settings"]["height"]) == (1080, 1920)
    res = await auth_client.patch(f"/api/projects/{pid}/sequence", json={"reframe_mode": "off"})
    assert res.json()["document"]["settings"]["reframe"] is None


def test_numpy_available() -> None:
    assert np.__version__
