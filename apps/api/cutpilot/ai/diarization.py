"""Speaker diarization via pyannote.audio (optional). Falls back to a single speaker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cutpilot.ai.transcription import Segment
from cutpilot.core.config import get_settings
from cutpilot.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str


def diarize(audio_path: Path) -> list[SpeakerTurn] | None:
    """Return speaker turns, or None when diarization is disabled/unavailable."""
    s = get_settings()
    if not s.local_diarization_enabled:
        return None
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError:
        log.warning("diarization_unavailable", reason="pyannote.audio not installed")
        return None
    if not s.hf_token:
        log.warning("diarization_unavailable", reason="HF_TOKEN missing")
        return None
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=s.hf_token
        )
        if s.whisper_device == "cuda" and torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
        diarization = pipeline(str(audio_path))
    except Exception as exc:
        log.warning("diarization_failed", error=str(exc))
        return None
    turns = [
        SpeakerTurn(start=round(t.start, 3), end=round(t.end, 3), speaker=str(label))
        for t, _, label in diarization.itertracks(yield_label=True)
    ]
    return sorted(turns, key=lambda t: t.start)


def assign_speakers(segments: list[Segment], turns: list[SpeakerTurn] | None) -> list[str]:
    """Label words/segments with speakers by maximum temporal overlap. Returns the speaker labels used."""
    if not turns:
        for seg in segments:
            seg.speaker = "SPEAKER_00"
            for w in seg.words:
                w.speaker = "SPEAKER_00"
        return ["SPEAKER_00"]
    labels: set[str] = set()

    def best(start: float, end: float) -> str:
        best_label, best_overlap = turns[0].speaker, -1.0
        for t in turns:
            if t.end < start:
                continue
            if t.start > end:
                break
            overlap = min(end, t.end) - max(start, t.start)
            if overlap > best_overlap:
                best_label, best_overlap = t.speaker, overlap
        return best_label

    for seg in segments:
        for w in seg.words:
            w.speaker = best(w.start, w.end)
            labels.add(w.speaker)
        if seg.words:
            counts: dict[str, int] = {}
            for w in seg.words:
                counts[w.speaker or ""] = counts.get(w.speaker or "", 0) + 1
            seg.speaker = max(counts, key=lambda k: counts[k])
        else:
            seg.speaker = best(seg.start, seg.end)
        labels.add(seg.speaker)
    return sorted(labels)
