"""Shot / scene boundary detection with PySceneDetect."""

from __future__ import annotations

from pathlib import Path

from cutpilot.core.errors import MediaProcessingError


def detect_scenes(
    video_path: Path,
    *,
    threshold: float = 27.0,
    min_scene_len_seconds: float = 1.0,
    duration: float | None = None,
) -> list[dict[str, float]]:
    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:
        raise MediaProcessingError("PySceneDetect is not installed") from exc
    try:
        scene_list = detect(
            str(video_path),
            ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len_seconds * 30)),
            show_progress=False,
        )
    except Exception as exc:
        raise MediaProcessingError(f"scene detection failed: {exc}") from exc
    scenes: list[dict[str, float]] = []
    for i, (start, end) in enumerate(scene_list):
        scenes.append(
            {"index": i, "start": round(start.get_seconds(), 3), "end": round(end.get_seconds(), 3)}
        )
    if not scenes and duration:
        scenes.append({"index": 0, "start": 0.0, "end": round(duration, 3)})
    return scenes


def sample_times_for_scenes(
    scenes: list[dict[str, float]],
    *,
    per_scene: int = 2,
    long_scene_interval: float = 45.0,
    max_frames: int = 60,
) -> list[float]:
    """Representative timestamps: 1-3 per scene plus periodic samples inside long scenes."""
    times: list[float] = []
    for s in scenes:
        length = s["end"] - s["start"]
        if length <= 0:
            continue
        if length < 3:
            times.append(s["start"] + length / 2)
        elif length <= long_scene_interval:
            n = min(per_scene, 3)
            times.extend(s["start"] + length * (i + 1) / (n + 1) for i in range(n))
        else:
            t = s["start"] + long_scene_interval / 2
            while t < s["end"]:
                times.append(t)
                t += long_scene_interval
    times = sorted({round(t, 2) for t in times})
    if len(times) > max_frames:
        step = len(times) / max_frames
        times = [times[int(i * step)] for i in range(max_frames)]
    return times
