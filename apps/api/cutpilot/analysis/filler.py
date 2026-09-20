"""Filler-word detection over word-level transcript timestamps."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cutpilot.core.constants import DEFAULT_FILLER_WORDS

_PUNCT = re.compile(r"[^\w' ]+")


def normalize(text: str) -> str:
    return _PUNCT.sub("", text.lower()).strip()


@dataclass
class FillerHit:
    start: float
    end: float
    text: str
    word_indices: list[int]


def detect_fillers(
    words: list[dict[str, float | str]], filler_words: list[str] | None = None
) -> list[FillerHit]:
    """`words` items: {"start","end","text"} in transcript order. Multi-word phrases supported."""
    phrases = [
        normalize(p).split() for p in (filler_words or list(DEFAULT_FILLER_WORDS)) if normalize(p)
    ]
    phrases.sort(key=len, reverse=True)
    norm = [normalize(str(w["text"])) for w in words]
    hits: list[FillerHit] = []
    i = 0
    while i < len(words):
        matched = False
        for phrase in phrases:
            n = len(phrase)
            if n and norm[i : i + n] == phrase:
                # "like" / "actually" / "literally" are only fillers when not clearly semantic; we keep the
                # rule simple and deterministic: standalone match, and let the user tune the list.
                hits.append(
                    FillerHit(
                        start=float(words[i]["start"]),
                        end=float(words[i + n - 1]["end"]),
                        text=" ".join(str(words[k]["text"]) for k in range(i, i + n)),
                        word_indices=list(range(i, i + n)),
                    )
                )
                i += n
                matched = True
                break
        if not matched:
            i += 1
    return hits


def filler_cut_segments(
    hits: list[FillerHit], *, padding: float = 0.04, merge_gap: float = 0.25
) -> list[dict[str, float | str]]:
    """Cut ranges (slightly tightened, merged when adjacent) from filler hits."""
    out: list[dict[str, float | str]] = []
    for h in hits:
        start, end = round(h.start + padding, 3), round(h.end - padding, 3)
        if end <= start:
            start, end = round(h.start, 3), round(h.end, 3)
        if out and start - float(out[-1]["end"]) <= merge_gap:
            out[-1]["end"] = end
            out[-1]["text"] = f"{out[-1]['text']} {h.text}"
        else:
            out.append({"start": start, "end": end, "text": h.text})
    return out
