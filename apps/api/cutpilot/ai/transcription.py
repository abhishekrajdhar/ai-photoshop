"""Transcription providers: OpenAI API (default), WhisperX and faster-whisper (optional local)."""

from __future__ import annotations

import abc
import math
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cutpilot.core.config import get_settings
from cutpilot.core.errors import AIConfigurationError, AIProviderError
from cutpilot.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class Word:
    start: float
    end: float
    text: str
    confidence: float | None = None
    speaker: str | None = None


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    confidence: float | None = None
    speaker: str | None = None


@dataclass
class TranscriptResult:
    provider: str
    model: str
    language: str | None
    text: str
    segments: list[Segment]
    cost_usd: float = 0.0
    latency_ms: int = 0

    def confidence(self) -> float | None:
        vals = [w.confidence for s in self.segments for w in s.words if w.confidence is not None]
        return round(sum(vals) / len(vals), 4) if vals else None


class TranscriptionProvider(abc.ABC):
    name: str
    model: str

    @abc.abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> TranscriptResult: ...


# ── OpenAI ───────────────────────────────────────────────────────────────────

CHUNK_SECONDS = 600  # 10 min of 16 kHz mono PCM ≈ 19 MB, under the 25 MB API limit


def _audio_duration(path: Path) -> float:
    from cutpilot.media.ffmpeg import ffprobe

    return ffprobe(path).duration


def _split_audio(
    path: Path, work: Path, chunk_seconds: int = CHUNK_SECONDS
) -> list[tuple[Path, float]]:
    """Split audio into chunks (mp3 to keep uploads small). Returns [(chunk_path, offset_seconds)]."""
    duration = _audio_duration(path)
    n = max(1, math.ceil(duration / chunk_seconds))
    out: list[tuple[Path, float]] = []
    settings = get_settings()
    for i in range(n):
        offset = i * chunk_seconds
        dst = work / f"chunk_{i:03d}.mp3"
        subprocess.run(
            [
                settings.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(offset),
                "-t",
                str(chunk_seconds),
                "-i",
                str(path),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "48k",
                str(dst),
            ],
            check=True,
        )
        out.append((dst, float(offset)))
    return out


class OpenAITranscription(TranscriptionProvider):
    name = "openai"

    def __init__(self) -> None:
        from openai import OpenAI

        s = get_settings()
        if not s.openai_api_key:
            raise AIConfigurationError("OPENAI_API_KEY is required for OpenAI transcription")
        self.client = OpenAI(api_key=s.openai_api_key, timeout=600, max_retries=s.ai_max_retries)
        self.model = s.openai_transcription_model

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> TranscriptResult:
        import time

        from cutpilot.ai.pricing import estimate_transcription_cost

        started = time.perf_counter()
        segments: list[Segment] = []
        detected_language: str | None = None
        with tempfile.TemporaryDirectory(dir=get_settings().work_dir) as tmp:
            chunks = _split_audio(audio_path, Path(tmp))
            for i, (chunk, offset) in enumerate(chunks):
                with chunk.open("rb") as fh:
                    kwargs: dict[str, Any] = {
                        "model": self.model,
                        "file": fh,
                        "response_format": "verbose_json",
                        "timestamp_granularities": ["word", "segment"],
                    }
                    if language:
                        kwargs["language"] = language
                    try:
                        res = self.client.audio.transcriptions.create(**kwargs)
                    except Exception as exc:
                        raise AIProviderError(f"OpenAI transcription failed: {exc}") from exc
                data = res.model_dump() if hasattr(res, "model_dump") else dict(res)
                detected_language = detected_language or data.get("language")
                words = [
                    Word(
                        start=round(float(w["start"]) + offset, 3),
                        end=round(float(w["end"]) + offset, 3),
                        text=str(w["word"]).strip(),
                    )
                    for w in data.get("words") or []
                ]
                for seg in data.get("segments") or []:
                    s_start, s_end = (
                        round(float(seg["start"]) + offset, 3),
                        round(float(seg["end"]) + offset, 3),
                    )
                    seg_words = [
                        w for w in words if w.start >= s_start - 0.05 and w.end <= s_end + 0.05
                    ]
                    conf = None
                    if seg.get("avg_logprob") is not None:
                        conf = round(min(1.0, max(0.0, math.exp(float(seg["avg_logprob"])))), 4)
                    for w in seg_words:
                        w.confidence = conf
                    segments.append(
                        Segment(
                            start=s_start,
                            end=s_end,
                            text=str(seg["text"]).strip(),
                            words=seg_words,
                            confidence=conf,
                        )
                    )
                if not data.get("segments") and words:
                    segments.extend(_segments_from_words(words))
                if on_progress:
                    on_progress((i + 1) / len(chunks))
        minutes = _audio_duration(audio_path) / 60
        return TranscriptResult(
            provider=self.name,
            model=self.model,
            language=detected_language,
            text=" ".join(s.text for s in segments).strip(),
            segments=segments,
            cost_usd=estimate_transcription_cost(self.model, minutes),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _segments_from_words(
    words: list[Word], max_words: int = 18, max_gap: float = 1.0
) -> list[Segment]:
    segments: list[Segment] = []
    current: list[Word] = []
    for w in words:
        if current and (
            len(current) >= max_words
            or w.start - current[-1].end > max_gap
            or current[-1].text.endswith((".", "?", "!"))
        ):
            segments.append(
                Segment(
                    start=current[0].start,
                    end=current[-1].end,
                    text=" ".join(x.text for x in current),
                    words=current,
                )
            )
            current = []
        current.append(w)
    if current:
        segments.append(
            Segment(
                start=current[0].start,
                end=current[-1].end,
                text=" ".join(x.text for x in current),
                words=current,
            )
        )
    return segments


# ── faster-whisper (optional local) ──────────────────────────────────────────


class FasterWhisperTranscription(TranscriptionProvider):
    name = "faster_whisper"

    def __init__(self) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise AIConfigurationError(
                "faster-whisper is not installed; pip install 'cutpilot-api[local-ai]'"
            ) from exc
        s = get_settings()
        self.model = s.whisper_model_size
        compute = "float16" if s.whisper_device == "cuda" else "int8"
        self._model = WhisperModel(self.model, device=s.whisper_device, compute_type=compute)

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> TranscriptResult:
        import time

        started = time.perf_counter()
        duration = _audio_duration(audio_path)
        seg_iter, info = self._model.transcribe(
            str(audio_path), language=language, word_timestamps=True, vad_filter=True
        )
        segments: list[Segment] = []
        for seg in seg_iter:
            words = [
                Word(
                    start=round(w.start, 3),
                    end=round(w.end, 3),
                    text=w.word.strip(),
                    confidence=round(float(w.probability), 4),
                )
                for w in (seg.words or [])
            ]
            segments.append(
                Segment(
                    start=round(seg.start, 3),
                    end=round(seg.end, 3),
                    text=seg.text.strip(),
                    words=words,
                    confidence=round(math.exp(seg.avg_logprob), 4) if seg.avg_logprob else None,
                )
            )
            if on_progress and duration:
                on_progress(min(0.99, seg.end / duration))
        return TranscriptResult(
            provider=self.name,
            model=self.model,
            language=info.language,
            text=" ".join(s.text for s in segments),
            segments=segments,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


# ── WhisperX (optional local, best word alignment) ───────────────────────────


class WhisperXTranscription(TranscriptionProvider):
    name = "whisperx"

    def __init__(self) -> None:
        try:
            import whisperx  # noqa: F401
        except ImportError as exc:
            raise AIConfigurationError(
                "whisperx is not installed; pip install 'cutpilot-api[local-ai]'"
            ) from exc
        s = get_settings()
        self.model = s.whisper_model_size
        self.device = s.whisper_device

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> TranscriptResult:
        import time

        import whisperx

        started = time.perf_counter()
        compute = "float16" if self.device == "cuda" else "int8"
        model = whisperx.load_model(
            self.model, self.device, compute_type=compute, language=language
        )
        audio = whisperx.load_audio(str(audio_path))
        result = model.transcribe(audio, batch_size=8)
        if on_progress:
            on_progress(0.6)
        lang = result.get("language") or language
        align_model, meta = whisperx.load_align_model(language_code=lang, device=self.device)
        aligned = whisperx.align(
            result["segments"], align_model, meta, audio, self.device, return_char_alignments=False
        )
        segments: list[Segment] = []
        for seg in aligned["segments"]:
            words = [
                Word(
                    start=round(float(w.get("start", seg["start"])), 3),
                    end=round(float(w.get("end", seg["end"])), 3),
                    text=str(w["word"]).strip(),
                    confidence=round(float(w.get("score", 0.0)), 4)
                    if w.get("score") is not None
                    else None,
                )
                for w in seg.get("words", [])
                if w.get("word")
            ]
            segments.append(
                Segment(
                    start=round(float(seg["start"]), 3),
                    end=round(float(seg["end"]), 3),
                    text=str(seg["text"]).strip(),
                    words=words,
                )
            )
        if on_progress:
            on_progress(0.95)
        return TranscriptResult(
            provider=self.name,
            model=self.model,
            language=lang,
            text=" ".join(s.text for s in segments),
            segments=segments,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def get_transcription_provider() -> TranscriptionProvider:
    """Order: explicitly enabled local provider → OpenAI API → faster-whisper if installed (auto)."""
    s = get_settings()
    if s.local_transcription_enabled and s.transcription_provider != "openai":
        try:
            return (
                WhisperXTranscription()
                if s.transcription_provider == "whisperx"
                else FasterWhisperTranscription()
            )
        except AIConfigurationError as exc:
            log.warning("local_transcription_unavailable", error=str(exc))
    if s.openai_api_key:
        return OpenAITranscription()
    try:
        provider = FasterWhisperTranscription()
        log.info("transcription_auto_local", model=provider.model)
        return provider
    except AIConfigurationError:
        pass
    raise AIConfigurationError(
        "No transcription provider available: set OPENAI_API_KEY or install faster-whisper "
        "(pip install 'cutpilot-api[local-transcription]')"
    )


def transcription_available() -> bool:
    s = get_settings()
    if s.openai_api_key or s.local_transcription_enabled:
        return True
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        return False
