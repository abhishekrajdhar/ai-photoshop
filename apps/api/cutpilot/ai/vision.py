"""Frame-sampled video understanding via vision-capable LLMs (provider-agnostic)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from cutpilot.ai.prompts import render_prompt
from cutpilot.ai.providers.base import ImagePart, Message
from cutpilot.ai.router import AIRouter

BATCH_SIZE = 8


class FrameQuality(BaseModel):
    sharpness: float = 0.5
    exposure: str = "good"
    framing: float = 0.5


class FrameAnalysis(BaseModel):
    t: float
    description: str = ""
    people_count: int = 0
    faces_visible: bool = False
    main_subject_position: str = "none"
    shot_type: str = "other"
    objects: list[str] = Field(default_factory=list)
    environment: str = "unknown"
    action: str = ""
    visible_text: str = ""
    quality: FrameQuality = Field(default_factory=FrameQuality)
    composition_notes: str = ""
    issues: list[str] = Field(default_factory=list)
    thumbnail_candidate: float = 0.0
    broll_worthy: bool = False


class EditingOpportunity(BaseModel):
    t: float
    suggestion: str
    confidence: float = 0.5


class VisionBatch(BaseModel):
    frames: list[FrameAnalysis] = Field(default_factory=list)
    scene_description: str = ""
    editing_opportunities: list[EditingOpportunity] = Field(default_factory=list)


class VisionProvider:
    """Interface described in the spec: analyze_frames / describe_scene / detect_editing_opportunities."""

    def __init__(self, router: AIRouter, *, context: str = ""):
        self.router = router
        self.context = context

    def analyze_frames(
        self,
        frames: list[tuple[float, Path]],
        *,
        on_progress: Callable[[float], None] | None = None,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        scene_descriptions: list[dict[str, Any]] = []
        opportunities: list[dict[str, Any]] = []
        batches = [frames[i : i + BATCH_SIZE] for i in range(0, len(frames), BATCH_SIZE)]
        for i, batch in enumerate(batches):
            images = [ImagePart.from_file(p, label=f"frame at {t:.1f}s") for t, p in batch]
            prompt = render_prompt("vision_frames", context=self.context)
            parsed, _ = self.router.complete_structured(
                VisionBatch,
                operation="vision",
                messages=[Message(role="user", content=prompt, images=images)],
                purpose="vision",
                max_tokens=3500,
                meta={"batch": i, "frames": len(batch)},
            )
            # Snap returned timestamps to the frames we actually sent.
            sent = [t for t, _ in batch]
            for f in parsed.frames:
                f.t = min(sent, key=lambda s: abs(s - f.t))
            results.extend(f.model_dump() for f in parsed.frames)
            scene_descriptions.append(
                {"start": sent[0], "end": sent[-1], "description": parsed.scene_description}
            )
            opportunities.extend(o.model_dump() for o in parsed.editing_opportunities)
            if on_progress:
                on_progress(0.3 + 0.65 * (i + 1) / len(batches))
        results.sort(key=lambda f: f["t"])
        return {
            "frames": results,
            "scenes": scene_descriptions,
            "editing_opportunities": sorted(opportunities, key=lambda o: o["t"]),
        }

    def describe_scene(self, frames: list[tuple[float, Path]]) -> str:
        data = self.analyze_frames(frames)
        return " ".join(s["description"] for s in data["scenes"])

    def detect_editing_opportunities(
        self, frames: list[tuple[float, Path]]
    ) -> list[dict[str, Any]]:
        return self.analyze_frames(frames)["editing_opportunities"]
