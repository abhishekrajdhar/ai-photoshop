"""Silence detection and loudness measurement using ffmpeg filters (deterministic)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cutpilot.media.ffmpeg import run_ffmpeg_capture

_START = re.compile(r"silence_start:\s*([0-9.]+)")
_END = re.compile(r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)")


def detect_silence(
    audio_path: Path,
    *,
    threshold_db: float = -35.0,
    min_duration: float = 0.8,
    total_duration: float | None = None,
) -> list[dict[str, float]]:
    stderr = run_ffmpeg_capture(
        [
            "-i",
            str(audio_path),
            "-af",
            f"silencedetect=noise={threshold_db}dB:d={min_duration}",
            "-f",
            "null",
            "-",
        ]
    )
    segments: list[dict[str, float]] = []
    pending: float | None = None
    for line in stderr.splitlines():
        m = _START.search(line)
        if m:
            pending = float(m.group(1))
            continue
        m = _END.search(line)
        if m and pending is not None:
            end = float(m.group(1))
            segments.append(
                {
                    "start": round(pending, 3),
                    "end": round(end, 3),
                    "duration": round(end - pending, 3),
                }
            )
            pending = None
    if pending is not None and total_duration:
        segments.append(
            {
                "start": round(pending, 3),
                "end": round(total_duration, 3),
                "duration": round(total_duration - pending, 3),
            }
        )
    return segments


def measure_loudness(audio_path: Path) -> dict[str, Any]:
    """EBU R128 stats via loudnorm's analysis pass + peak/mean volume from volumedetect."""
    out: dict[str, Any] = {}
    stderr = run_ffmpeg_capture(
        [
            "-i",
            str(audio_path),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    start, end = stderr.rfind("{"), stderr.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(stderr[start : end + 1])
            out["integrated_lufs"] = float(data.get("input_i", "nan"))
            out["true_peak_dbtp"] = float(data.get("input_tp", "nan"))
            out["loudness_range_lu"] = float(data.get("input_lra", "nan"))
            out["threshold"] = float(data.get("input_thresh", "nan"))
        except (ValueError, TypeError):
            pass
    stderr = run_ffmpeg_capture(["-i", str(audio_path), "-af", "volumedetect", "-f", "null", "-"])
    for key, pat in (
        ("mean_volume_db", r"mean_volume:\s*(-?[0-9.]+)"),
        ("max_volume_db", r"max_volume:\s*(-?[0-9.]+)"),
    ):
        m = re.search(pat, stderr)
        if m:
            out[key] = float(m.group(1))
    return out


def suggest_silence_cuts(
    segments: list[dict[str, float]], *, keep_padding: float = 0.15, min_cut: float = 0.5
) -> list[dict[str, float]]:
    """Convert detected silences into conservative cut ranges that keep a natural breath."""
    cuts: list[dict[str, float]] = []
    for s in segments:
        start = s["start"] + keep_padding
        end = s["end"] - keep_padding
        if end - start >= min_cut:
            cuts.append(
                {"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)}
            )
    return cuts
