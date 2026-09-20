"""Proxy (720p H.264), thumbnail, audio extraction and waveform generation."""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np

from cutpilot.core.config import get_settings
from cutpilot.core.errors import MediaProcessingError
from cutpilot.media.ffmpeg import MediaInfo, run_ffmpeg


def make_proxy(
    src: Path,
    dst: Path,
    info: MediaInfo,
    on_progress: Callable[[float], None] | None = None,
    check_cancel: Callable[[], bool] | None = None,
) -> str:
    """Encode a lightweight H.264/AAC proxy with the configured height (default 720p)."""
    settings = get_settings()
    h = settings.proxy_height
    w, hh = info.display_size
    # Keep aspect; never upscale; even dimensions for yuv420p.
    scale = (
        f"scale='if(gt(ih,{h}),-2,iw)':'if(gt(ih,{h}),{h},ih)'"
        if (hh or 0) > 0
        else f"scale=-2:{h}"
    )
    if w and hh and w < hh:  # portrait: bound the width instead
        scale = f"scale='if(gt(iw,{h}),{h},iw)':'if(gt(iw,{h}),-2,ih)'"
    args = [
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        f"{scale},format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-maxrate",
        settings.proxy_video_bitrate,
        "-bufsize",
        "5M",
        "-g",
        "48",
        "-keyint_min",
        "48",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    return run_ffmpeg(
        args, duration=info.duration, on_progress=on_progress, check_cancel=check_cancel
    )


def make_audio_proxy(
    src: Path, dst: Path, info: MediaInfo, on_progress: Callable[[float], None] | None = None
) -> str:
    """Audio-only assets get an AAC 'proxy' for browser playback."""
    args = [
        "-i",
        str(src),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    return run_ffmpeg(args, duration=info.duration, on_progress=on_progress)


def extract_audio(
    src: Path,
    dst: Path,
    info: MediaInfo,
    *,
    sample_rate: int = 16000,
    on_progress: Callable[[float], None] | None = None,
) -> str:
    """Mono 16 kHz PCM WAV — ideal for ASR and analysis."""
    args = [
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    return run_ffmpeg(args, duration=info.duration, on_progress=on_progress)


def make_thumbnail(src: Path, dst: Path, *, at: float = 0.0, width: int = 640) -> str:
    args = [
        "-ss",
        f"{max(0.0, at):.3f}",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-q:v",
        "3",
        str(dst),
    ]
    return run_ffmpeg(args)


def make_image_thumbnail(src: Path, dst: Path, *, width: int = 640) -> str:
    args = ["-i", str(src), "-vf", f"scale={width}:-2", "-q:v", "3", str(dst)]
    return run_ffmpeg(args)


def extract_frames(src: Path, out_dir: Path, times: list[float], *, width: int = 768) -> list[Path]:
    """Extract one JPEG per timestamp (used for vision analysis and thumbnails candidates)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, t in enumerate(times):
        dst = out_dir / f"frame_{i:04d}_{t:.2f}.jpg"
        run_ffmpeg(
            [
                "-ss",
                f"{max(0.0, t):.3f}",
                "-i",
                str(src),
                "-frames:v",
                "1",
                "-vf",
                f"scale={width}:-2",
                "-q:v",
                "4",
                str(dst),
            ]
        )
        paths.append(dst)
    return paths


def compute_waveform_peaks(src: Path, *, peaks_per_second: int = 20) -> dict[str, object]:
    """Downsampled absolute peaks for waveform rendering, computed from decoded PCM."""
    settings = get_settings()
    sr = 8000
    cmd = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "pipe:1",
    ]
    try:
        raw = subprocess.run(cmd, capture_output=True, check=True, timeout=1800).stdout
    except subprocess.CalledProcessError as exc:
        raise MediaProcessingError(
            f"waveform decode failed: {exc.stderr.decode(errors='ignore')[-400:]}"
        ) from exc
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        return {"sample_rate": peaks_per_second, "peaks": [], "duration": 0.0}
    window = max(1, sr // peaks_per_second)
    n = math.ceil(samples.size / window)
    padded = np.zeros(n * window, dtype=np.float32)
    padded[: samples.size] = np.abs(samples)
    peaks = padded.reshape(n, window).max(axis=1)
    rms = np.sqrt((padded.reshape(n, window) ** 2).mean(axis=1))
    return {
        "sample_rate": peaks_per_second,
        "duration": round(samples.size / sr, 3),
        "peaks": [round(float(p), 3) for p in peaks],
        "rms": [round(float(r), 3) for r in rms],
    }


def dumps_waveform(data: dict[str, object]) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode()
