"""Locate a TrueType font for caption rasterisation (Inter → DejaVu → Arial → system fallbacks)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

CANDIDATES = [
    "/usr/share/fonts/truetype/inter/Inter-SemiBold.ttf",
    "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
    "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


@lru_cache
def find_font(preferred: str | None = None) -> str | None:
    env = os.environ.get("CAPTION_FONT_PATH")
    if env and Path(env).is_file():
        return env
    if preferred:
        for c in CANDIDATES:
            if (
                preferred.lower().replace(" ", "") in Path(c).name.lower().replace(" ", "")
                and Path(c).is_file()
            ):
                return c
    for c in CANDIDATES:
        if Path(c).is_file():
            return c
    return None
