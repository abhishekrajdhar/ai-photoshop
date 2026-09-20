"""Thumbnail candidate scoring: sharpness, exposure, face visibility/size, framing and text-safe area."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2

from cutpilot.media.reframe import FaceDetector


def score_frame(path: Path) -> dict[str, Any]:
    img = cv2.imread(str(path))
    if img is None:
        return {"score": 0.0, "factors": {}, "error": "unreadable"}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharpness = min(1.0, sharp / 400.0)
    mean = float(gray.mean()) / 255.0
    exposure = 1.0 - min(1.0, abs(mean - 0.5) / 0.5)
    contrast = min(1.0, float(gray.std()) / 64.0)
    try:
        faces = [f for f in FaceDetector().detect(img) if f[2] >= w * 0.05]
    except Exception:
        faces = []
    face_visibility = 0.0
    framing = 0.5
    text_safe = 1.0
    face_box = None
    if len(faces):
        x, y, fw, fh, _score = max(faces, key=lambda f: f[2] * f[3])
        face_box = {
            "x": round(x / w, 3),
            "y": round(y / h, 3),
            "w": round(fw / w, 3),
            "h": round(fh / h, 3),
        }
        size_frac = fw / w
        face_visibility = min(1.0, size_frac / 0.25)
        cx = (x + fw / 2) / w
        # Rule-of-thirds friendliness: faces near a third line score higher than dead centre or edges
        framing = 1.0 - min(1.0, min(abs(cx - 1 / 3), abs(cx - 2 / 3), abs(cx - 0.5) * 1.5) / 0.33)
        # Text-safe: the larger empty side (for a title) is valuable
        text_safe = max(x / w, 1 - (x + fw) / w)
    factors = {
        "sharpness": round(sharpness, 3),
        "exposure": round(exposure, 3),
        "contrast": round(contrast, 3),
        "face_visibility": round(face_visibility, 3),
        "framing": round(framing, 3),
        "text_safe_area": round(text_safe, 3),
    }
    score = (
        0.3 * sharpness
        + 0.15 * exposure
        + 0.1 * contrast
        + 0.25 * face_visibility
        + 0.1 * framing
        + 0.1 * text_safe
    )
    return {"score": round(score, 4), "factors": factors, "face": face_box}


def candidate_times(
    duration: float,
    scenes: list[dict[str, float]],
    key_times: list[float],
    *,
    max_candidates: int = 24,
) -> list[float]:
    times: set[float] = set()
    for s in scenes:
        length = s["end"] - s["start"]
        if length > 0:
            times.add(round(s["start"] + length * 0.35, 2))
            if length > 30:
                times.add(round(s["start"] + length * 0.7, 2))
    for t in key_times:
        times.add(round(min(max(0.0, t + 0.6), max(0.0, duration - 0.1)), 2))
    if not times and duration > 0:
        times.update(round(duration * f, 2) for f in (0.1, 0.3, 0.5, 0.7, 0.9))
    ordered = sorted(times)
    if len(ordered) > max_candidates:
        step = len(ordered) / max_candidates
        ordered = [ordered[int(i * step)] for i in range(max_candidates)]
    return ordered
