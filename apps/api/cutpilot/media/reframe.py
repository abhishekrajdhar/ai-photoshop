"""Subject tracking for auto-reframe: OpenCV face detection on sampled frames → smoothed keyframes.

Keyframes are in SOURCE time of the asset ({"t", "x", "y"} with x/y as normalised centre 0..1) and are
mapped to timeline time when a document is rendered.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from cutpilot.core.config import get_settings
from cutpilot.core.errors import MediaProcessingError
from cutpilot.timeline.model import TimelineDocument


@dataclass
class TrackConfig:
    sample_fps: float = 2.0
    smoothing: float = 0.35  # EMA factor (higher = follows faster)
    max_jump: float = (
        0.25  # ignore detections that jump more than this fraction of the frame per sample
    )
    min_face_frac: float = 0.04  # minimum face width as a fraction of frame width


MODEL_FILE = "face_detection_yunet_2023mar.onnx"


def model_path() -> Path:
    """Vendored YuNet face detector (Apache-2.0, OpenCV Zoo)."""
    return Path(__file__).parent / "models" / MODEL_FILE


class FaceDetector:
    """Thin wrapper over cv2.FaceDetectorYN returning (x, y, w, h, score) boxes in pixels."""

    def __init__(self, score_threshold: float = 0.7):
        if not hasattr(cv2, "FaceDetectorYN"):
            raise MediaProcessingError("OpenCV FaceDetectorYN is not available in this build")
        if not model_path().is_file():
            raise MediaProcessingError("YuNet face model is missing")
        self._det = cv2.FaceDetectorYN.create(
            str(model_path()), "", (320, 320), score_threshold, 0.3, 200
        )
        self._size: tuple[int, int] | None = None

    def detect(self, bgr: np.ndarray) -> list[tuple[int, int, int, int, float]]:
        h, w = bgr.shape[:2]
        if self._size != (w, h):
            self._det.setInputSize((w, h))
            self._size = (w, h)
        _, faces = self._det.detect(bgr)
        if faces is None:
            return []
        return [(int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[-1])) for f in faces]


def _iter_frames(video: Path, fps: float, width: int = 480):
    """Yield (t, bgr_frame) sampled at `fps` using ffmpeg piping raw frames (no OpenCV codec dependency)."""
    settings = get_settings()
    probe = (
        subprocess.run(
            [
                settings.ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(video),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .split(",")
    )
    sw, sh = int(probe[0]), int(probe[1])
    h = max(2, round(width * sh / sw / 2) * 2)
    cmd = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"fps={fps},scale={width}:{h}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    frame_bytes = width * h * 3
    i = 0
    try:
        while True:
            buf = b""
            while len(buf) < frame_bytes:  # pipes may return short reads
                chunk = proc.stdout.read(frame_bytes - len(buf))
                if not chunk:
                    break
                buf += chunk
            if len(buf) < frame_bytes:
                break
            yield i / fps, np.frombuffer(buf, dtype=np.uint8).reshape(h, width, 3)
            i += 1
    finally:
        proc.kill()


def track_subject(
    video: Path, *, duration: float, config: TrackConfig | None = None
) -> dict[str, Any]:
    """Return {"keyframes": [{"t","x","y","w"}], "coverage": fraction of samples with a face}."""
    cfg = config or TrackConfig()
    det = FaceDetector()
    raw: list[tuple[float, float | None, float | None, float | None]] = []
    for t, frame in _iter_frames(video, cfg.sample_fps):
        h, w = frame.shape[:2]
        faces = [f for f in det.detect(frame) if f[2] >= w * cfg.min_face_frac]
        if not faces:
            raw.append((t, None, None, None))
            continue
        x, y, fw, fh, _score = max(faces, key=lambda f: f[2] * f[3])
        raw.append((t, (x + fw / 2) / w, (y + fh / 2) / h, fw / w))
    if not raw:
        return {
            "keyframes": [{"t": 0.0, "x": 0.5, "y": 0.5, "w": 0.0}],
            "coverage": 0.0,
            "sample_fps": cfg.sample_fps,
        }
    # Smooth: EMA over detections, hold the last position through gaps, reject wild jumps.
    keyframes: list[dict[str, float]] = []
    cx, cy = 0.5, 0.5
    seen = False
    detected = 0
    for t, x, y, fw in raw:
        if x is not None and y is not None:
            detected += 1
            if not seen:
                cx, cy, seen = x, y, True
            elif abs(x - cx) <= cfg.max_jump:
                cx += cfg.smoothing * (x - cx)
                cy += cfg.smoothing * (y - cy)
            else:  # large jump: move faster but not instantly
                cx += 0.6 * (x - cx)
                cy += 0.6 * (y - cy)
        keyframes.append(
            {
                "t": round(t, 3),
                "x": round(min(1.0, max(0.0, cx)), 4),
                "y": round(min(1.0, max(0.0, cy)), 4),
                "w": round(fw or 0.0, 4),
            }
        )
    if duration > 0 and keyframes[-1]["t"] < duration:
        keyframes.append({**keyframes[-1], "t": round(duration, 3)})
    return {
        "keyframes": keyframes,
        "coverage": round(detected / len(raw), 3),
        "sample_fps": cfg.sample_fps,
    }


def timeline_reframe_keyframes(
    doc: TimelineDocument, tracks_by_asset: dict[str, list[dict[str, float]]], *, step: float = 0.5
) -> list[dict[str, float]]:
    """Map per-asset source keyframes onto the document's timeline for the primary video track."""
    out: list[dict[str, float]] = []
    for clip in doc.primary_video_track().sorted_clips():
        kfs = tracks_by_asset.get(clip.asset_id or "")
        if not kfs:
            out.append({"t": round(clip.timeline_start, 3), "x": 0.5, "y": 0.5})
            continue
        ts = np.array([k["t"] for k in kfs])
        xs = np.array([k["x"] for k in kfs])
        ys = np.array([k["y"] for k in kfs])
        t = clip.timeline_start
        while t < clip.timeline_end - 1e-6:
            s = clip.timeline_to_source(t)
            out.append(
                {
                    "t": round(t, 3),
                    "x": round(float(np.interp(s, ts, xs)), 4),
                    "y": round(float(np.interp(s, ts, ys)), 4),
                }
            )
            t += step
        s_end = clip.timeline_to_source(clip.timeline_end)
        out.append(
            {
                "t": round(clip.timeline_end, 3),
                "x": round(float(np.interp(s_end, ts, xs)), 4),
                "y": round(float(np.interp(s_end, ts, ys)), 4),
            }
        )
    # de-duplicate times
    dedup: list[dict[str, float]] = []
    for k in out:
        if dedup and abs(dedup[-1]["t"] - k["t"]) < 1e-6:
            dedup[-1] = k
        else:
            dedup.append(k)
    return dedup
