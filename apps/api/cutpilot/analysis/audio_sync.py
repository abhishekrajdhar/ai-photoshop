"""Waveform synchronisation for multicam: estimate the offset between two recordings by cross-correlation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from cutpilot.core.config import get_settings


def load_mono(path: Path, sr: int = 8000, max_seconds: float = 600.0) -> np.ndarray:
    cmd = [
        get_settings().ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-t",
        str(max_seconds),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "pipe:1",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def envelope(x: np.ndarray, sr: int, hop: int = 80) -> np.ndarray:
    """Onset-ish envelope: RMS in 10 ms hops, log-compressed, mean removed."""
    n = len(x) // hop
    if n == 0:
        return np.zeros(1, dtype=np.float32)
    frames = x[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames**2).mean(axis=1) + 1e-9)
    env = np.log1p(rms * 50)
    return (env - env.mean()).astype(np.float32)


def estimate_offset(
    reference: Path,
    other: Path,
    *,
    sr: int = 8000,
    hop: int = 80,
    max_offset_seconds: float = 120.0,
) -> dict[str, float]:
    """Return {"offset": seconds to add to `other` so it aligns with `reference`, "confidence": 0..1}."""
    a = envelope(load_mono(reference, sr), sr, hop)
    b = envelope(load_mono(other, sr), sr, hop)
    n = len(a) + len(b)
    size = 1 << (n - 1).bit_length()
    fa = np.fft.rfft(a, size)
    fb = np.fft.rfft(b, size)
    corr = np.fft.irfft(fa * np.conj(fb), size)
    corr = np.concatenate(
        [corr[-len(b) + 1 :], corr[: len(a)]]
    )  # lags from -(len(b)-1) .. len(a)-1
    lags = np.arange(-len(b) + 1, len(a))
    max_lag = int(max_offset_seconds * sr / hop)
    mask = np.abs(lags) <= max_lag
    corr, lags = corr[mask], lags[mask]
    if corr.size == 0:
        return {"offset": 0.0, "confidence": 0.0}
    best = int(np.argmax(corr))
    peak = float(corr[best])
    rest = np.delete(corr, best)
    noise = float(np.abs(rest).mean() + 1e-9)
    confidence = float(min(1.0, max(0.0, (peak / noise - 1) / 20)))
    offset = float(lags[best]) * hop / sr
    return {"offset": round(offset, 3), "confidence": round(confidence, 3)}
