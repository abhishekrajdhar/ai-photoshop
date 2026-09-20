"""Deterministic fakes for AI providers used in tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cutpilot.ai.providers.base import LLMProvider, LLMResponse, Message, ToolSpec
from cutpilot.ai.transcription import Segment, TranscriptionProvider, TranscriptResult, Word


class FakeTranscription(TranscriptionProvider):
    name = "fake"
    model = "fake-1"

    def __init__(
        self,
        text: str = "Hello world um this is a test. Basically we are testing the pipeline. Okay so like that is it.",
    ) -> None:
        self.text = text

    def transcribe(self, audio_path: Path, *, language=None, on_progress=None) -> TranscriptResult:  # type: ignore[no-untyped-def]
        sentences = [s.strip() for s in self.text.split(".") if s.strip()]
        t = 0.0
        segments: list[Segment] = []
        for sent in sentences:
            words = []
            for w in sent.split():
                words.append(Word(start=round(t, 3), end=round(t + 0.4, 3), text=w, confidence=0.9))
                t += 0.5
            segments.append(
                Segment(
                    start=words[0].start,
                    end=words[-1].end,
                    text=sent + ".",
                    words=words,
                    confidence=0.9,
                )
            )
            t += 1.0
        return TranscriptResult(
            provider=self.name,
            model=self.model,
            language="en",
            text=" ".join(s.text for s in segments),
            segments=segments,
        )


class FakeLLM(LLMProvider):
    """Returns schema-shaped JSON depending on the schema name; records calls."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[str, Any] = {}
        self.invalid_first = False

    def default_model(self, purpose):  # type: ignore[no-untyped-def]
        return "fake-model"

    def complete(
        self,
        *,
        messages: list[Message],
        system=None,
        json_schema=None,
        schema_name="response",
        tools: list[ToolSpec] | None = None,
        max_tokens=4096,
        temperature=0.2,
        model=None,
    ) -> LLMResponse:  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "schema": schema_name,
                "messages": len(messages),
                "tools": [t.name for t in tools or []],
                "images": sum(len(m.images) for m in messages),
            }
        )
        if self.invalid_first and len(self.calls) == 1:
            return LLMResponse(
                provider=self.name,
                model="fake-model",
                text='{"chapters": "nope"}',
                json={"chapters": "nope"},
                input_tokens=10,
                output_tokens=5,
            )
        payload = self.responses.get(schema_name)
        if payload is None:
            payload = DEFAULT_RESPONSES.get(schema_name, {})
        if callable(payload):
            payload = payload(messages)
        return LLMResponse(
            provider=self.name,
            model="fake-model",
            text=json.dumps(payload),
            json=payload,
            input_tokens=100,
            output_tokens=50,
            latency_ms=5,
        )


DEFAULT_RESPONSES: dict[str, Any] = {
    "SectionAnalysis": {
        "summary": "A short test section.",
        "topics": ["testing", "pipeline"],
        "key_statements": [
            {"start": 0.0, "end": 2.0, "text": "Hello world", "importance": 0.8, "kind": "hook"}
        ],
        "hooks": [{"start": 0.0, "end": 2.0, "text": "Hello world", "reason": "opening"}],
        "weak_segments": [{"start": 8.0, "end": 9.5, "reason": "filler-heavy"}],
        "repeated_statements": [],
        "tangents": [],
        "strong_segments": [{"start": 4.0, "end": 7.0, "reason": "clear"}],
        "removable_candidates": [{"start": 8.0, "end": 9.5, "reason": "filler", "confidence": 0.7}],
        "short_form_moments": [
            {"start": 0.0, "end": 7.0, "reason": "self-contained", "score": 0.8}
        ],
        "broll_opportunities": [
            {"start": 4.0, "end": 6.0, "query": "software testing", "reason": "abstract"}
        ],
    },
    "ProjectSummary": {
        "title_suggestions": ["Testing the pipeline"],
        "summary": "A test video.",
        "topics": ["testing"],
        "chapters": [
            {"start": 0.0, "end": 5.0, "title": "Intro"},
            {"start": 5.0, "end": 12.0, "title": "Testing"},
        ],
        "best_hooks": [{"start": 0.0, "end": 2.0, "text": "Hello world", "reason": "opening"}],
        "structure_notes": "linear",
        "pacing_notes": "fine",
        "audience": "devs",
        "tone": "educational",
    },
    "VisionBatch": lambda messages: {
        "frames": [
            {
                "t": 0.0,
                "description": "test pattern",
                "people_count": 0,
                "faces_visible": False,
                "shot_type": "graphic",
                "environment": "unknown",
                "quality": {"sharpness": 0.9, "exposure": "good", "framing": 0.5},
                "thumbnail_candidate": 0.3,
            }
            for _ in range(sum(len(m.images) for m in messages))
        ],
        "scene_description": "colour bars",
        "editing_opportunities": [{"t": 1.0, "suggestion": "add lower third", "confidence": 0.4}],
    },
}
