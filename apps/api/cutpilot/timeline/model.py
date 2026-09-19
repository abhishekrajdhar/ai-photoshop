"""Timeline document model — the source of truth for every edit.

The document is a JSON-serialisable, non-destructive description of tracks and clips
that reference immutable media assets by id and source time range. It is stored as a
snapshot per `TimelineVersion` and can be exported to OpenTimelineIO.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

TrackKind = Literal["video", "audio", "caption", "overlay"]
ClipKind = Literal["video", "audio", "image", "caption", "text", "broll", "music"]
EffectType = Literal[
    "zoom",
    "crop",
    "reframe",
    "fade_video",
    "fade_audio",
    "audio_gain",
    "noise_reduction",
    "voice_enhancement",
    "normalize_audio",
    "blur",
    "object_blur",
    "face_blur",
    "color_adjustment",
    "lut",
    "stabilization",
    "speed",
    "ducking",
]
TransitionType = Literal["cut", "crossfade", "fade_black", "dip_to_white"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class TLModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Effect(TLModel):
    id: str = Field(default_factory=lambda: new_id("fx"))
    type: EffectType
    # Times are relative to the clip's timeline start. None = whole clip.
    start: float | None = None
    duration: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class Transition(TLModel):
    type: TransitionType = "cut"
    duration: float = 0.0


class CaptionStyle(TLModel):
    font: str = "Inter"
    font_size: int = 42
    color: str = "#FFFFFF"
    highlight_color: str = "#FFD700"
    background: str | None = None
    outline: float = 2.0
    outline_color: str = "#000000"
    shadow: float = 1.0
    position: Literal["top", "center", "bottom"] = "bottom"
    alignment: Literal["left", "center", "right"] = "center"
    margin_v: int = 60
    animation: Literal["none", "karaoke", "pop", "word"] = "none"
    uppercase: bool = False
    max_words_per_cue: int = 6
    preset: str = "clean"


class Clip(TLModel):
    id: str = Field(default_factory=lambda: new_id("clip"))
    kind: ClipKind
    name: str = ""
    asset_id: str | None = None
    # Position on the timeline (seconds)
    timeline_start: float = 0.0
    duration: float = 0.0
    # Source range within the asset (seconds). For images/text these are 0..duration.
    source_in: float = 0.0
    source_out: float = 0.0
    speed: float = 1.0
    gain_db: float = 0.0
    muted: bool = False
    # Text payload for caption/text clips
    text: str | None = None
    words: list[dict[str, Any]] | None = None  # [{"text","start","end"}] relative to clip start
    style: dict[str, Any] = Field(default_factory=dict)
    # Overlay geometry, normalised 0..1 (x, y, w, h)
    position: dict[str, float] | None = None
    effects: list[Effect] = Field(default_factory=list)
    transition_in: Transition = Field(default_factory=Transition)
    transition_out: Transition = Field(default_factory=Transition)
    # Links an audio clip to its video clip (or vice versa) so they move/cut together.
    linked_clip_id: str | None = None
    # Loop the asset to fill `duration` (music)
    loop: bool = False
    fade_in: float = 0.0
    fade_out: float = 0.0
    ducking: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def timeline_end(self) -> float:
        return self.timeline_start + self.duration

    def source_duration(self) -> float:
        return max(0.0, self.source_out - self.source_in)

    def timeline_to_source(self, t: float) -> float:
        """Map a timeline time (absolute) inside this clip to a source time."""
        return self.source_in + (t - self.timeline_start) * self.speed

    def source_to_timeline(self, s: float) -> float:
        return self.timeline_start + (s - self.source_in) / self.speed

    def recompute_duration(self) -> None:
        if self.kind in ("video", "audio", "broll", "music") and self.asset_id and not self.loop:
            self.duration = round(self.source_duration() / max(self.speed, 1e-6), 6)


class Track(TLModel):
    id: str = Field(default_factory=lambda: new_id("track"))
    kind: TrackKind
    name: str
    index: int = 0
    muted: bool = False
    locked: bool = False
    hidden: bool = False
    clips: list[Clip] = Field(default_factory=list)

    def sorted_clips(self) -> list[Clip]:
        return sorted(self.clips, key=lambda c: c.timeline_start)


class Marker(TLModel):
    id: str = Field(default_factory=lambda: new_id("mk"))
    time: float
    label: str = ""
    color: str = "#7C3AED"
    kind: str = "marker"  # marker | chapter | broll_suggestion
    meta: dict[str, Any] = Field(default_factory=dict)


class TimelineSettings(TLModel):
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    aspect_ratio: str = "16:9"
    background: str = "#000000"
    sample_rate: int = 48000
    caption_style: CaptionStyle = Field(default_factory=CaptionStyle)
    # Global audio processing applied at render time
    audio: dict[str, Any] = Field(
        default_factory=dict
    )  # {"normalize": true, "noise_reduction": true, ...}
    # Auto-reframe configuration: {"mode": "center"|"track", "keyframes": [{"t","x","y"}]}
    reframe: dict[str, Any] | None = None


class TimelineDocument(TLModel):
    schema_version: int = SCHEMA_VERSION
    timeline_id: str
    name: str = "Main"
    settings: TimelineSettings = Field(default_factory=TimelineSettings)
    tracks: list[Track] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    # ── construction ──────────────────────────────────────────────────────
    @classmethod
    def empty(
        cls, *, timeline_id: str, name: str = "Main", settings: TimelineSettings | None = None
    ) -> TimelineDocument:
        return cls(
            timeline_id=timeline_id,
            name=name,
            settings=settings or TimelineSettings(),
            tracks=[
                Track(id="V1", kind="video", name="Video 1", index=0),
                Track(id="V2", kind="video", name="Video 2", index=1),
                Track(id="A1", kind="audio", name="Audio 1", index=2),
                Track(id="A2", kind="audio", name="Audio 2", index=3),
                Track(id="C1", kind="caption", name="Captions", index=4),
            ],
        )

    # ── lookup helpers ────────────────────────────────────────────────────
    def track(self, track_id: str) -> Track:
        for t in self.tracks:
            if t.id == track_id:
                return t
        raise KeyError(f"track {track_id} not found")

    def tracks_of_kind(self, kind: TrackKind) -> list[Track]:
        return sorted([t for t in self.tracks if t.kind == kind], key=lambda t: t.index)

    def primary_video_track(self) -> Track:
        return self.tracks_of_kind("video")[0]

    def primary_audio_track(self) -> Track:
        return self.tracks_of_kind("audio")[0]

    def caption_track(self) -> Track:
        tracks = self.tracks_of_kind("caption")
        if tracks:
            return tracks[0]
        track = Track(id="C1", kind="caption", name="Captions", index=len(self.tracks))
        self.tracks.append(track)
        return track

    def find_clip(self, clip_id: str) -> tuple[Track, Clip]:
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    return t, c
        raise KeyError(f"clip {clip_id} not found")

    def all_clips(self) -> list[tuple[Track, Clip]]:
        return [(t, c) for t in self.tracks for c in t.clips]

    def duration(self) -> float:
        ends = [c.timeline_end for t in self.tracks for c in t.clips]
        return round(max(ends), 6) if ends else 0.0

    def clip_at(self, track: Track, t: float) -> Clip | None:
        for c in track.sorted_clips():
            if c.timeline_start <= t < c.timeline_end:
                return c
        return None

    def asset_ids(self) -> set[str]:
        return {c.asset_id for _, c in self.all_clips() if c.asset_id}

    def clips_for_asset(self, asset_id: str) -> list[tuple[Track, Clip]]:
        return [(t, c) for t, c in self.all_clips() if c.asset_id == asset_id]

    def timeline_to_source_ranges(
        self, asset_id: str, start: float, end: float
    ) -> list[tuple[float, float]]:
        """Return source ranges of `asset_id` visible in timeline range [start, end)."""
        out: list[tuple[float, float]] = []
        for _, c in self.clips_for_asset(asset_id):
            a, b = max(start, c.timeline_start), min(end, c.timeline_end)
            if b > a:
                out.append((c.timeline_to_source(a), c.timeline_to_source(b)))
        return out

    def source_to_timeline_ranges(
        self, asset_id: str, start: float, end: float, kinds: tuple[str, ...] = ("video",)
    ) -> list[tuple[float, float]]:
        """Map a source range of an asset to the timeline ranges where it is currently used."""
        out: list[tuple[float, float]] = []
        for t, c in self.clips_for_asset(asset_id):
            if t.kind not in kinds:
                continue
            a, b = max(start, c.source_in), min(end, c.source_out)
            if b > a:
                out.append((c.source_to_timeline(a), c.source_to_timeline(b)))
        return sorted(out)

    def sort(self) -> None:
        for t in self.tracks:
            t.clips.sort(key=lambda c: c.timeline_start)


def merge_ranges(ranges: list[tuple[float, float]], gap: float = 0.0) -> list[tuple[float, float]]:
    """Merge overlapping / adjacent [start, end) ranges."""
    if not ranges:
        return []
    ordered = sorted((min(a, b), max(a, b)) for a, b in ranges)
    merged = [ordered[0]]
    for a, b in ordered[1:]:
        la, lb = merged[-1]
        if a <= lb + gap:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return [(round(a, 6), round(b, 6)) for a, b in merged if b > a]
