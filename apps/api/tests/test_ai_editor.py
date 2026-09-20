"""Planner validation/expansion, chat tool loop, proposal preview/apply/reject (fake providers)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.fakes import DEFAULT_RESPONSES, FakeTranscription, ScriptedLLM
from tests.media_fixtures import make_test_video
from tests.test_media import _upload


def _install(monkeypatch: pytest.MonkeyPatch, llm: ScriptedLLM) -> None:
    from cutpilot.ai import router, transcription
    from cutpilot.workers.tasks import analysis as tasks

    monkeypatch.setattr(router, "available_providers", lambda: ["openai"])
    monkeypatch.setattr(router, "_provider", lambda name: llm)
    monkeypatch.setattr(transcription, "get_transcription_provider", lambda: FakeTranscription())
    monkeypatch.setattr(tasks, "get_transcription_provider", lambda: FakeTranscription())


async def _prepared_project(auth_client: AsyncClient, tmp_path: Path) -> tuple[str, str]:
    pid = (await auth_client.post("/api/projects", json={"name": "ai"})).json()["id"]
    video = make_test_video(tmp_path / "talk.mp4", duration=12)
    asset = (await _upload(auth_client, pid, video))["asset"]
    res = await auth_client.post(
        f"/api/projects/{pid}/analyze", json={"steps": ["transcription", "audio", "content"]}
    )
    assert res.status_code == 200
    return pid, asset["id"]


PLAN_JSON = {
    "summary": "Remove pauses and filler words, add captions, one emphasis zoom.",
    "operations": [
        {
            "type": "silence_removal",
            "params": {"auto": True},
            "reason": "pauses",
            "confidence": 0.95,
        },
        {
            "type": "filler_word_removal",
            "params": {"auto": True},
            "reason": "fillers",
            "confidence": 0.9,
        },
        {
            "type": "caption",
            "params": {"auto": True, "style": {"preset": "clean"}},
            "reason": "captions",
            "confidence": 1.0,
        },
        {
            "type": "zoom",
            "timestamp": 2.0,
            "duration": 2.0,
            "scale": 1.12,
            "reason": "hook",
            "confidence": 0.7,
        },
        {
            "type": "remove_segment",
            "start": 50.0,
            "end": 60.0,
            "reason": "outside media (should be rejected)",
            "confidence": 0.5,
        },
    ],
    "estimated_duration_delta": None,
    "warnings": [],
}


async def test_direct_edit_planner_expands_macros_and_applies(
    auth_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = ScriptedLLM(
        [
            {"json": DEFAULT_RESPONSES["SectionAnalysis"]},
            {"json": DEFAULT_RESPONSES["ProjectSummary"]},
            {"json": PLAN_JSON},
        ]
    )
    _install(monkeypatch, llm)
    pid, _asset_id = await _prepared_project(auth_client, tmp_path)

    res = await auth_client.post(
        f"/api/projects/{pid}/edit", json={"instruction": "Tighten this up and add captions"}
    )
    assert res.status_code == 200, res.text
    mid = res.json()["assistant_message"]["id"]
    msg = (await auth_client.get(f"/api/projects/{pid}/chat/messages/{mid}")).json()
    proposal = msg["proposal"]
    assert proposal["status"] == "proposed", proposal
    types = [o["type"] for o in proposal["operations"]]
    # fillers expanded from analysis; captions expanded from transcript words; zoom kept; out-of-range cut rejected
    assert "filler_word_removal" in types and types.count("caption") >= 2 and "zoom" in types
    assert any("50" in str(r["operation"].get("start")) for r in proposal["rejected"])
    assert all(o["source"] == "ai" for o in proposal["operations"])
    assert (
        proposal["estimated_duration_delta"] is not None
        and proposal["estimated_duration_delta"] < 0
    )
    # Silence macro produced a note (no pauses in synthetic audio)
    assert any("silence" in w.lower() for w in proposal["warnings"])

    # Preview does not change the timeline
    before = (await auth_client.get(f"/api/projects/{pid}/timeline")).json()
    prev = await auth_client.post(f"/api/projects/{pid}/chat/messages/{mid}/preview")
    assert prev.status_code == 200
    assert prev.json()["duration_after"] < prev.json()["duration_before"]
    assert prev.json()["removed_ranges"]
    assert (await auth_client.get(f"/api/projects/{pid}/timeline")).json()["version"][
        "id"
    ] == before["version"]["id"]

    # Apply creates an AI version with recorded operations
    applied = await auth_client.post(f"/api/projects/{pid}/chat/messages/{mid}/apply")
    assert applied.status_code == 200, applied.text
    state = applied.json()["state"]
    assert state["version"]["source"] == "ai" and state["version"]["operation_count"] >= 3
    assert state["version"]["duration"] < before["version"]["duration"]
    assert applied.json()["message"]["proposal"]["status"] == "applied"
    caption_clips = next(t for t in state["document"]["tracks"] if t["kind"] == "caption")["clips"]
    assert caption_clips and caption_clips[0]["words"]
    # Applying twice is refused
    assert (
        await auth_client.post(f"/api/projects/{pid}/chat/messages/{mid}/apply")
    ).status_code == 422


async def test_chat_tool_loop_and_reject(
    auth_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = ScriptedLLM(
        [
            {"json": DEFAULT_RESPONSES["SectionAnalysis"]},
            {"json": DEFAULT_RESPONSES["ProjectSummary"]},
            # chat round 1: inspect, then stage two tools
            {
                "tool_calls": [
                    ("get_audio_analysis", {}),
                    ("get_transcript", {"start": 0, "end": 5}),
                ]
            },
            {
                "tool_calls": [
                    ("remove_filler_words", {}),
                    (
                        "add_zoom",
                        {"timestamp": 3.0, "duration": 2, "scale": 1.1, "reason": "key point"},
                    ),
                    ("render_video", {"preset": "youtube_1080p"}),
                ]
            },
            {"text": "I found 3 filler words and staged a zoom at 3s. Apply when ready."},
        ]
    )
    _install(monkeypatch, llm)
    pid, _ = await _prepared_project(auth_client, tmp_path)

    res = await auth_client.post(
        f"/api/projects/{pid}/chat",
        json={"message": "Remove the ums and add a zoom on the key point"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    mid = body["assistant_message"]["id"]
    msg = (await auth_client.get(f"/api/projects/{pid}/chat/messages/{mid}")).json()
    assert msg["content"].startswith("I found 3 filler words")
    assert [t["name"] for t in msg["tool_calls"]] == [
        "get_audio_analysis",
        "get_transcript",
        "remove_filler_words",
        "add_zoom",
        "render_video",
    ]
    p = msg["proposal"]
    assert p["status"] == "proposed" and {o["type"] for o in p["operations"]} == {
        "filler_word_removal",
        "zoom",
    }
    assert p["side_effects"] == [{"kind": "render", "preset": "youtube_1080p"}]
    # tool messages reached the model (assistant + tool roles in history)
    assert llm.calls[-1]["last_role"] == "tool"

    rejected = await auth_client.post(f"/api/projects/{pid}/chat/messages/{mid}/reject")
    assert rejected.json()["proposal"]["status"] == "rejected"
    sessions = (await auth_client.get(f"/api/projects/{pid}/chat/sessions")).json()
    assert len(sessions) == 1 and len(sessions[0]["messages"]) == 2
    assert sessions[0]["title"].startswith("Remove the ums")


async def test_chat_without_ai_configured_fails_gracefully(
    auth_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cutpilot.ai import router

    monkeypatch.setattr(router, "available_providers", lambda: [])
    pid = (await auth_client.post("/api/projects", json={"name": "noai"})).json()["id"]
    video = make_test_video(tmp_path / "talk.mp4", duration=3)
    await _upload(auth_client, pid, video)
    res = await auth_client.post(f"/api/projects/{pid}/chat", json={"message": "hi"})
    mid = res.json()["assistant_message"]["id"]
    msg = (await auth_client.get(f"/api/projects/{pid}/chat/messages/{mid}")).json()
    assert msg["proposal"]["status"] == "failed" and "No AI provider configured" in msg["content"]


def test_caption_cue_builder() -> None:
    from cutpilot.ai.expansion import build_caption_cues

    words = [
        {"start": i * 0.5, "end": i * 0.5 + 0.4, "text": t, "is_filler": t == "um"}
        for i, t in enumerate("Hello um world this is a test. Second sentence here now ok".split())
    ]
    cues = build_caption_cues(words, max_words=4)
    assert cues[0]["text"] == "Hello world this is"  # filler skipped, max 4 words
    assert cues[1]["text"] == "a test."  # sentence end breaks the cue
    assert cues[0]["words"][0]["start"] == 0.0 and cues[0]["start"] == 0.0


def test_planner_context_reduces_long_transcripts() -> None:
    from cutpilot.ai.context import ProjectContext, select_transcript

    segs = [
        {
            "start": i * 4.0,
            "end": i * 4.0 + 3.5,
            "text": (
                "we talk about kubernetes scaling "
                if i % 50 == 0
                else "filler talk about nothing important "
            )
            * 8,
        }
        for i in range(400)
    ]
    ctx = ProjectContext(
        project=None,
        asset=None,
        duration=1600.0,
        document=None,
        transcript_segments=segs,
        content={
            "sections": [
                {"section_start": 0, "section_end": 800, "summary": "first half", "topics": ["k8s"]}
            ]
        },
    )  # type: ignore[arg-type]
    text, note = select_transcript(ctx, "Make a short about kubernetes scaling", budget_words=2000)
    assert note.startswith("reduced")
    assert "kubernetes" in text and text.count("[") < 200
