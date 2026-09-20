"""Generate tiny synthetic media files with ffmpeg for tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def make_test_video(
    path: Path,
    *,
    duration: float = 3.0,
    width: int = 320,
    height: int = 180,
    fps: int = 25,
    with_audio: bool = True,
) -> Path:
    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate={fps}:duration={duration}",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={duration}"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        args += ["-c:a", "aac", "-shortest"]
    args += [str(path)]
    subprocess.run(args, check=True)
    return path


def make_test_audio(path: Path, *, duration: float = 3.0) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=44100:duration={duration}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
    )
    return path


def make_test_image(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )
    return path


def make_speech_like_audio(path: Path, *, pattern: list[tuple[float, bool]]) -> Path:
    """Build audio from (duration, loud?) segments — loud = tone, quiet = near silence."""
    parts = []
    for i, (dur, loud) in enumerate(pattern):
        src = (
            f"sine=frequency=300:sample_rate=16000:duration={dur}"
            if loud
            else f"anullsrc=r=16000:cl=mono:d={dur}"
        )
        parts.append(src)
    inputs: list[str] = []
    for src in parts:
        inputs += ["-f", "lavfi", "-i", src]
    n = len(parts)
    filter_complex = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
    )
    return path
