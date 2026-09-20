"""Export presets. `custom` accepts explicit settings."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ExportPreset:
    id: str
    name: str
    description: str
    width: int
    height: int
    fps: float | None  # None = keep sequence fps
    video_bitrate: str
    audio_bitrate: str
    codec: str = "libx264"
    aspect_ratio: str = "16:9"
    crf: int = 18
    preset: str = "medium"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PRESETS: dict[str, ExportPreset] = {
    "youtube_1080p": ExportPreset(
        "youtube_1080p",
        "YouTube 1080p",
        "1920x1080 H.264, 12 Mb/s, AAC 192k",
        1920,
        1080,
        None,
        "12M",
        "192k",
    ),
    "youtube_4k": ExportPreset(
        "youtube_4k",
        "YouTube 4K",
        "3840x2160 H.264, 45 Mb/s, AAC 256k",
        3840,
        2160,
        None,
        "45M",
        "256k",
        crf=17,
    ),
    "instagram_reel": ExportPreset(
        "instagram_reel",
        "Instagram Reel",
        "1080x1920 vertical, 8 Mb/s",
        1080,
        1920,
        30,
        "8M",
        "160k",
        aspect_ratio="9:16",
    ),
    "tiktok": ExportPreset(
        "tiktok",
        "TikTok",
        "1080x1920 vertical, 8 Mb/s",
        1080,
        1920,
        30,
        "8M",
        "160k",
        aspect_ratio="9:16",
    ),
    "youtube_shorts": ExportPreset(
        "youtube_shorts",
        "YouTube Shorts",
        "1080x1920 vertical, 10 Mb/s",
        1080,
        1920,
        30,
        "10M",
        "192k",
        aspect_ratio="9:16",
    ),
    "podcast": ExportPreset(
        "podcast",
        "Podcast",
        "1280x720, 3 Mb/s, AAC 192k (audio-first)",
        1280,
        720,
        30,
        "3M",
        "192k",
        crf=23,
        preset="fast",
    ),
    "preview": ExportPreset(
        "preview",
        "Preview",
        "720p fast draft render",
        1280,
        720,
        None,
        "2500k",
        "128k",
        crf=26,
        preset="veryfast",
    ),
    "custom": ExportPreset(
        "custom",
        "Custom",
        "Choose resolution, fps, bitrate and codec",
        1920,
        1080,
        None,
        "12M",
        "192k",
    ),
}


def resolve_preset(preset_id: str, overrides: dict[str, object] | None = None) -> ExportPreset:
    base = PRESETS.get(preset_id, PRESETS["custom"])
    data = base.to_dict()
    for key in (
        "width",
        "height",
        "fps",
        "video_bitrate",
        "audio_bitrate",
        "codec",
        "aspect_ratio",
        "crf",
        "preset",
    ):
        if overrides and overrides.get(key) not in (None, ""):
            data[key] = overrides[key]
    data["width"] = int(data["width"]) // 2 * 2
    data["height"] = int(data["height"]) // 2 * 2
    if data["codec"] not in ("libx264", "libx265", "libvpx-vp9"):
        data["codec"] = "libx264"
    return ExportPreset(**data)  # type: ignore[arg-type]
