"""Thin, deterministic wrappers around ffmpeg / ffprobe subprocesses."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cutpilot.core.config import get_settings
from cutpilot.core.errors import MediaProcessingError
from cutpilot.core.logging import get_logger

log = get_logger(__name__)

_TIME_RE = re.compile(r"out_time_ms=(\d+)")
_TIME_US_RE = re.compile(r"out_time_us=(\d+)")


@dataclass
class MediaInfo:
    container: str | None
    duration: float
    bitrate: int | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    audio_channels: int | None
    sample_rate: int | None
    rotation: int = 0
    has_video: bool = False
    has_audio: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def display_size(self) -> tuple[int | None, int | None]:
        if self.rotation in (90, 270, -90) and self.width and self.height:
            return self.height, self.width
        return self.width, self.height


def _parse_fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    if "/" in rate:
        num, den = rate.split("/")
        return round(float(num) / float(den), 3) if float(den) else None
    return float(rate)


def ffprobe(path: str | Path) -> MediaInfo:
    settings = get_settings()
    cmd = [
        settings.ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120).stdout
    except subprocess.CalledProcessError as exc:
        raise MediaProcessingError(f"ffprobe failed: {exc.stderr.strip()[:500]}") from exc
    except FileNotFoundError as exc:
        raise MediaProcessingError("ffprobe binary not found; set FFPROBE_PATH") from exc
    data = json.loads(out or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and s.get("disposition", {}).get("attached_pic", 0) == 0
        ),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    rotation = 0
    if video:
        tags = video.get("tags", {})
        try:
            rotation = int(float(tags.get("rotate", 0)))
        except (TypeError, ValueError):
            rotation = 0
        for sd in video.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rotation = int(float(sd["rotation"]))
                except (TypeError, ValueError):
                    pass
    duration = 0.0
    for candidate in (
        fmt.get("duration"),
        (video or {}).get("duration"),
        (audio or {}).get("duration"),
    ):
        try:
            if candidate is not None:
                duration = float(candidate)
                break
        except (TypeError, ValueError):
            continue
    is_image = bool(video) and (
        fmt.get("format_name", "").startswith(("image2", "png_pipe", "webp_pipe"))
        or (
            (video or {}).get("codec_name") in ("mjpeg", "png", "webp")
            and not audio
            and duration <= 0.1
        )
    )
    return MediaInfo(
        container=fmt.get("format_name"),
        duration=0.0 if is_image else round(duration, 3),
        bitrate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        fps=_parse_fps((video or {}).get("avg_frame_rate"))
        or _parse_fps((video or {}).get("r_frame_rate"))
        if video and not is_image
        else None,
        video_codec=(video or {}).get("codec_name"),
        audio_codec=(audio or {}).get("codec_name"),
        audio_channels=int(audio["channels"]) if audio and audio.get("channels") else None,
        sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        rotation=abs(rotation) % 360,
        has_video=bool(video) and not is_image,
        has_audio=bool(audio),
        raw={"format": fmt, "streams": streams, "is_image": is_image},
    )


def run_ffmpeg(
    args: list[str],
    *,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    timeout: int | None = None,
    check_cancel: Callable[[], bool] | None = None,
) -> str:
    """Run ffmpeg with -progress parsing. Returns the command string (for logging/debugging)."""
    settings = get_settings()
    cmd = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        *args,
    ]
    cmd_str = " ".join(shlex.quote(c) for c in cmd)
    log.debug("ffmpeg_run", cmd=cmd_str)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as exc:
        raise MediaProcessingError("ffmpeg binary not found; set FFMPEG_PATH") from exc
    assert proc.stdout is not None
    last = -1.0
    try:
        for line in proc.stdout:
            if on_progress and duration and duration > 0:
                m = _TIME_US_RE.search(line) or _TIME_RE.search(line)
                if m:
                    scale = 1_000_000 if "out_time_us" in line else 1_000
                    t = int(m.group(1)) / scale
                    frac = max(0.0, min(0.999, t / duration))
                    if frac - last >= 0.01:
                        last = frac
                        on_progress(frac)
            if check_cancel and check_cancel():
                proc.kill()
                raise MediaProcessingError("cancelled")
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise MediaProcessingError("ffmpeg timed out") from exc
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.returncode != 0:
        log.error("ffmpeg_failed", code=proc.returncode, stderr=stderr[-2000:], cmd=cmd_str)
        raise MediaProcessingError(
            f"ffmpeg failed ({proc.returncode}): {stderr.strip()[-800:]}",
            details={"command": cmd_str},
        )
    return cmd_str


def run_ffmpeg_capture(args: list[str], timeout: int = 600) -> str:
    """Run ffmpeg and return stderr (for filters like silencedetect that report via logs)."""
    settings = get_settings()
    cmd = [settings.ffmpeg_path, "-hide_banner", "-nostdin", "-y", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise MediaProcessingError("ffmpeg binary not found; set FFMPEG_PATH") from exc
    if proc.returncode != 0:
        raise MediaProcessingError(f"ffmpeg failed: {proc.stderr.strip()[-800:]}")
    return proc.stderr
