"""Silence, filler, scene detection, transcription pipeline, content + vision analysis (fake providers)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from cutpilot.analysis.filler import detect_fillers, filler_cut_segments
from cutpilot.media.scenes import detect_scenes, sample_times_for_scenes
from cutpilot.media.silence import detect_silence, suggest_silence_cuts
from tests.fakes import FakeLLM, FakeTranscription
from tests.media_fixtures import make_speech_like_audio, make_test_video
from tests.test_media import _upload


def test_silence_detection_on_synthetic_audio(tmp_path: Path) -> None:
    wav = make_speech_like_audio(
        tmp_path / "s.wav",
        pattern=[(2.0, True), (1.5, False), (2.0, True), (0.3, False), (1.0, True)],
    )
    silences = detect_silence(wav, threshold_db=-35, min_duration=0.8, total_duration=6.8)
    assert len(silences) == 1
    assert silences[0]["start"] == pytest.approx(2.0, abs=0.1) and silences[0][
        "end"
    ] == pytest.approx(3.5, abs=0.1)
    cuts = suggest_silence_cuts(silences)
    assert cuts[0]["duration"] == pytest.approx(1.2, abs=0.1)


def test_filler_detection_multiword() -> None:
    words = [
        {"start": i * 0.5, "end": i * 0.5 + 0.4, "text": t}
        for i, t in enumerate("So um I think you know that basically works.".split())
    ]
    hits = detect_fillers(words)
    assert [h.text for h in hits] == ["um", "you know", "basically"]
    segs = filler_cut_segments(hits)
    assert len(segs) == 3 and segs[1]["start"] < segs[1]["end"]


def test_scene_detection_and_sampling(tmp_path: Path) -> None:
    video = make_test_video(tmp_path / "v.mp4", duration=3, with_audio=False)
    scenes = detect_scenes(video, duration=3.0)
    assert scenes and scenes[0]["start"] == 0.0
    times = sample_times_for_scenes(
        [{"start": 0, "end": 10}, {"start": 10, "end": 200}], max_frames=10
    )
    assert 2 <= len(times) <= 10 and all(0 < t < 200 for t in times)


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    from cutpilot.ai import router, transcription

    llm = FakeLLM()
    monkeypatch.setattr(router, "available_providers", lambda: ["openai"])
    monkeypatch.setattr(router, "_provider", lambda name: llm)
    monkeypatch.setattr(transcription, "get_transcription_provider", lambda: FakeTranscription())
    from cutpilot.workers.tasks import analysis as tasks

    monkeypatch.setattr(tasks, "get_transcription_provider", lambda: FakeTranscription())
    return llm


async def test_full_analysis_pipeline(
    auth_client: AsyncClient, tmp_path: Path, fake_ai: FakeLLM
) -> None:
    pid = (await auth_client.post("/api/projects", json={"name": "analysis"})).json()["id"]
    video = make_test_video(tmp_path / "talk.mp4", duration=4)
    asset = (await _upload(auth_client, pid, video))["asset"]
    assert asset["status"] == "ready"

    res = await auth_client.post(
        f"/api/projects/{pid}/analyze",
        json={"steps": ["transcription", "audio", "scenes", "content", "vision"]},
    )
    assert res.status_code == 200, res.text
    jobs = res.json()["jobs"]
    assert {j["type"] for j in jobs} == {
        "TRANSCRIPTION",
        "AUDIO_ANALYSIS",
        "SCENE_DETECTION",
        "CONTENT_ANALYSIS",
        "VISION_ANALYSIS",
    }
    for j in jobs:
        state = (await auth_client.get(f"/api/jobs/{j['id']}")).json()
        assert state["status"] == "COMPLETED", (j["type"], state["error"])

    # Transcript with words, speakers, and filler flags
    t = (await auth_client.get(f"/api/projects/{pid}/transcript")).json()
    assert t["provider"] == "fake" and t["language"] == "en"
    assert len(t["segments"]) == 3 and t["speakers"][0]["display_name"] == "Speaker 1"
    words = [w for s in t["segments"] for w in s["words"]]
    fillers = [w["text"] for w in words if w["is_filler"]]
    assert fillers == ["um", "Basically", "like"]

    # Analysis results (silence, filler, scenes, content, vision, audio_stats)
    results = (await auth_client.get(f"/api/projects/{pid}/analysis")).json()
    kinds = {r["kind"] for r in results}
    assert {"silence", "filler", "scenes", "content", "vision", "audio_stats"} <= kinds
    content = next(r for r in results if r["kind"] == "content")["data"]
    assert content["summary"]["chapters"][-1]["end"] == pytest.approx(
        4.0, abs=0.2
    )  # normalised to media duration
    assert content["aggregate"]["removable_candidates"][0]["reason"] == "filler"
    vision = next(r for r in results if r["kind"] == "vision")["data"]
    assert len(vision["frames"]) == len(vision["sampled_times"]) >= 1
    assert fake_ai.calls[-1]["images"] >= 1

    # Scenes + thumbnail
    scenes = (await auth_client.get(f"/api/projects/{pid}/scenes")).json()
    assert scenes and scenes[0]["thumbnail_url"]
    assert (await auth_client.get(scenes[0]["thumbnail_url"])).headers[
        "content-type"
    ] == "image/jpeg"

    # AI usage logged
    from sqlalchemy import select

    from cutpilot.db.models import AIRequest
    from cutpilot.db.session import get_async_session_factory

    async with get_async_session_factory()() as s:
        rows = (await s.execute(select(AIRequest))).scalars().all()
    ops = {r.operation for r in rows}
    assert {"transcription", "transcript_analysis", "transcript_summary", "vision"} <= ops

    # Transcript editing
    seg = t["segments"][0]
    res = await auth_client.patch(
        f"/api/projects/{pid}/transcript/segments/{seg['id']}",
        json={"text": "Hello there world um this is a test."},
    )
    assert res.status_code == 200 and len(res.json()["words"]) == 7
    res = await auth_client.patch(
        f"/api/projects/{pid}/transcript/speakers/{t['speakers'][0]['id']}",
        json={"display_name": "Host"},
    )
    assert res.json()["display_name"] == "Host"
    word = t["segments"][1]["words"][0]
    res = await auth_client.patch(
        f"/api/projects/{pid}/transcript/words/{word['id']}", json={"is_filler": True}
    )
    assert res.json()["is_filler"] is True

    # Re-running is served from cache (no new transcription call, job completes)
    res = await auth_client.post(f"/api/projects/{pid}/transcribe", json={})
    job = (await auth_client.get(f"/api/jobs/{res.json()['jobs'][0]['id']}")).json()
    assert job["status"] == "COMPLETED" and job["result"]["cached"] is True


async def test_structured_output_repair_loop(fake_ai: FakeLLM) -> None:
    from cutpilot.ai.providers.base import Message
    from cutpilot.ai.router import AIRouter
    from cutpilot.ai.transcript_analyzer import ProjectSummary

    fake_ai.invalid_first = True
    router = AIRouter(None)
    parsed, _ = router.complete_structured(
        ProjectSummary, operation="test", messages=[Message(role="user", content="x")]
    )
    assert parsed.topics == ["testing"]
    assert len(fake_ai.calls) == 2 and fake_ai.calls[1]["messages"] == 3  # repair turn appended


async def test_analysis_requires_footage(auth_client: AsyncClient, fake_ai: FakeLLM) -> None:
    pid = (await auth_client.post("/api/projects", json={"name": "empty"})).json()["id"]
    res = await auth_client.post(f"/api/projects/{pid}/analyze", json={"steps": ["transcription"]})
    assert res.status_code == 422


def test_router_reports_missing_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from cutpilot.ai import router
    from cutpilot.ai.providers.base import Message
    from cutpilot.core.errors import AIConfigurationError

    monkeypatch.setattr(router, "available_providers", lambda: [])
    with pytest.raises(AIConfigurationError):
        router.AIRouter(None).complete(operation="x", messages=[Message(role="user", content="hi")])
