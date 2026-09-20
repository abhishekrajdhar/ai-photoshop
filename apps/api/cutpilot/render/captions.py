"""Caption generation: SRT / VTT / ASS text formats and rasterised PNG cues for burn-in."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from cutpilot.render.fonts import find_font
from cutpilot.timeline.model import CaptionStyle, TimelineDocument

PRESETS: dict[str, dict[str, Any]] = {
    "clean": {
        "font_size": 42,
        "color": "#FFFFFF",
        "outline": 2.0,
        "shadow": 1.0,
        "position": "bottom",
        "animation": "none",
        "uppercase": False,
        "background": None,
    },
    "bold": {
        "font_size": 56,
        "color": "#FFFFFF",
        "outline": 3.0,
        "shadow": 2.0,
        "position": "bottom",
        "animation": "word",
        "uppercase": True,
        "background": None,
        "highlight_color": "#FFD400",
    },
    "karaoke": {
        "font_size": 52,
        "color": "#FFFFFF",
        "outline": 3.0,
        "shadow": 1.0,
        "position": "center",
        "animation": "karaoke",
        "uppercase": True,
        "highlight_color": "#7C5CFF",
        "background": None,
    },
    "minimal": {
        "font_size": 36,
        "color": "#FFFFFF",
        "outline": 0.0,
        "shadow": 0.0,
        "position": "bottom",
        "animation": "none",
        "background": "#000000AA",
        "uppercase": False,
    },
    "boxed": {
        "font_size": 44,
        "color": "#111111",
        "outline": 0.0,
        "shadow": 0.0,
        "position": "bottom",
        "animation": "none",
        "background": "#FFFFFFEE",
        "uppercase": False,
    },
}


def resolve_style(base: CaptionStyle, override: dict[str, Any] | None = None) -> CaptionStyle:
    data = base.model_dump()
    preset = (override or {}).get("preset") or base.preset
    if preset in PRESETS:
        data.update(PRESETS[preset])
        data["preset"] = preset
    if override:
        data.update({k: v for k, v in override.items() if v is not None and k in data})
    return CaptionStyle.model_validate(data)


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: list[dict[str, Any]] = field(default_factory=list)  # relative to start
    style: dict[str, Any] = field(default_factory=dict)


def caption_cues(doc: TimelineDocument) -> list[Cue]:
    cues: list[Cue] = []
    for track in doc.tracks_of_kind("caption"):
        if track.hidden:
            continue
        for c in track.sorted_clips():
            if not c.text:
                continue
            cues.append(
                Cue(
                    start=c.timeline_start,
                    end=c.timeline_end,
                    text=c.text,
                    words=c.words or [],
                    style=c.style or {},
                )
            )
    return sorted(cues, key=lambda c: c.start)


# ── text formats ─────────────────────────────────────────────────────────────


def _ts_srt(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_vtt(t: float) -> str:
    return _ts_srt(t).replace(",", ".")


def _ts_ass(t: float) -> str:
    cs = round(t * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def to_srt(cues: list[Cue]) -> str:
    return "\n".join(
        f"{i + 1}\n{_ts_srt(c.start)} --> {_ts_srt(c.end)}\n{c.text}\n" for i, c in enumerate(cues)
    ) + ("\n" if cues else "")


def to_vtt(cues: list[Cue]) -> str:
    body = "\n".join(f"{_ts_vtt(c.start)} --> {_ts_vtt(c.end)}\n{c.text}\n" for c in cues)
    return "WEBVTT\n\n" + body


def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = h[6:8] if len(h) == 8 else "00"
    alpha = f"{255 - int(a, 16):02X}" if len(h) == 8 else "00"
    return f"&H{alpha}{b}{g}{r}".upper()


def to_ass(cues: list[Cue], style: CaptionStyle, width: int, height: int) -> str:
    align = {"bottom": 2, "center": 5, "top": 8}[style.position]
    if style.alignment == "left":
        align -= 1
    elif style.alignment == "right":
        align += 1
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font},{style.font_size},{_ass_color(style.color)},{_ass_color(style.highlight_color)},{_ass_color(style.outline_color)},{_ass_color(style.background or "#00000080")},-1,0,0,0,100,100,0,0,{3 if style.background else 1},{style.outline},{style.shadow},{align},40,40,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in cues:
        text = c.text.upper() if style.uppercase else c.text
        if style.animation == "karaoke" and c.words:
            parts = []
            for w in c.words:
                dur_cs = max(1, round((w["end"] - w["start"]) * 100))
                parts.append(
                    f"{{\\k{dur_cs}}}{w['text'].upper() if style.uppercase else w['text']}"
                )
            text = " ".join(parts)
        lines.append(
            f"Dialogue: 0,{_ts_ass(c.start)},{_ts_ass(c.end)},Default,,0,0,0,,{text.replace(chr(10), ' ')}"
        )
    return header + "\n".join(lines) + "\n"


# ── PNG rasterisation for burn-in ────────────────────────────────────────────


def _hex_rgba(
    hex_color: str | None, default: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    if not hex_color:
        return default
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    if len(h) == 8:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    return default


@dataclass
class RasterCue:
    start: float
    end: float
    path: Path


def _load_font(style: CaptionStyle, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = find_font(style.font)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _wrap(
    draw: ImageDraw.ImageDraw, words: list[str], font: ImageFont.ImageFont, max_width: int
) -> list[list[int]]:
    """Return lines as lists of word indices that fit max_width."""
    lines: list[list[int]] = []
    current: list[int] = []
    for i, _w in enumerate(words):
        trial = " ".join(words[j] for j in [*current, i])
        if current and draw.textlength(trial, font=font) > max_width:
            lines.append(current)
            current = [i]
        else:
            current.append(i)
    if current:
        lines.append(current)
    return lines


def render_cue_image(
    text_words: list[str],
    highlight_index: int | None,
    style: CaptionStyle,
    width: int,
    height: int,
    out: Path,
    *,
    scale: float = 1.0,
) -> Path:
    """Rasterise one caption state (optionally with a highlighted word) to a transparent PNG."""
    size = max(12, int(style.font_size * scale))
    font = _load_font(style, size)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    words = [w.upper() for w in text_words] if style.uppercase else list(text_words)
    max_w = int(width * 0.86)
    lines = _wrap(draw, words, font, max_w)
    line_h = int(size * 1.25)
    total_h = line_h * len(lines)
    margin = int(style.margin_v * scale)
    if style.position == "top":
        y = margin
    elif style.position == "center":
        y = (height - total_h) // 2
    else:
        y = height - margin - total_h
    color = _hex_rgba(style.color, (255, 255, 255, 255))
    hl = _hex_rgba(style.highlight_color, (255, 212, 0, 255))
    outline_col = _hex_rgba(style.outline_color, (0, 0, 0, 255))
    stroke = round(style.outline * scale)
    bg = _hex_rgba(style.background, (0, 0, 0, 0)) if style.background else None
    if bg:
        widest = max(draw.textlength(" ".join(words[i] for i in ln), font=font) for ln in lines)
        pad = int(size * 0.35)
        bx0 = {
            "left": int(width * 0.07),
            "center": int((width - widest) / 2),
            "right": int(width * 0.93 - widest),
        }[style.alignment] - pad
        draw.rounded_rectangle(
            [bx0, y - pad // 2, bx0 + widest + 2 * pad, y + total_h + pad // 2],
            radius=int(size * 0.25),
            fill=bg,
        )
    for ln in lines:
        line_words = [words[i] for i in ln]
        line_text = " ".join(line_words)
        lw = draw.textlength(line_text, font=font)
        x = {
            "left": int(width * 0.07),
            "center": int((width - lw) / 2),
            "right": int(width * 0.93 - lw),
        }[style.alignment]
        cx = x
        for i, w in zip(ln, line_words, strict=True):
            fill = (
                hl
                if highlight_index is not None
                and i == highlight_index
                and style.animation in ("karaoke", "word", "pop")
                else color
            )
            if style.shadow > 0:
                off = round(style.shadow * scale) + 1
                draw.text(
                    (cx + off, y + off),
                    w,
                    font=font,
                    fill=(0, 0, 0, 160),
                    stroke_width=stroke,
                    stroke_fill=(0, 0, 0, 160),
                )
            draw.text(
                (cx, y), w, font=font, fill=fill, stroke_width=stroke, stroke_fill=outline_col
            )
            cx += draw.textlength(w + " ", font=font)
        y += line_h
    img.save(out, "PNG", optimize=False, compress_level=1)
    return out


def rasterize_cues(
    cues: list[Cue], base_style: CaptionStyle, width: int, height: int, out_dir: Path
) -> list[RasterCue]:
    """One PNG per visual state. Karaoke/word animations produce one image per word interval."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = height / 1080.0
    result: list[RasterCue] = []
    for ci, cue in enumerate(cues):
        style = resolve_style(base_style, cue.style)
        text_words = [w["text"] for w in cue.words] if cue.words else cue.text.split()
        if style.animation in ("karaoke", "word", "pop") and cue.words:
            t = cue.start
            for wi, w in enumerate(cue.words):
                w_start = cue.start + float(w["start"])
                w_end = cue.start + float(w["end"])
                if wi == 0:
                    w_start = cue.start
                if wi == len(cue.words) - 1:
                    w_end = cue.end
                w_start = max(t, w_start)
                if w_end <= w_start:
                    continue
                path = render_cue_image(
                    text_words,
                    wi,
                    style,
                    width,
                    height,
                    out_dir / f"cue_{ci:05d}_{wi:03d}.png",
                    scale=scale,
                )
                result.append(RasterCue(start=w_start, end=w_end, path=path))
                t = w_end
        else:
            path = render_cue_image(
                text_words, None, style, width, height, out_dir / f"cue_{ci:05d}.png", scale=scale
            )
            result.append(RasterCue(start=cue.start, end=cue.end, path=path))
    return result


def render_text_overlay_image(
    text: str,
    style: dict[str, Any],
    width: int,
    height: int,
    position: dict[str, float] | None,
    out: Path,
) -> Path:
    """Rasterise a text overlay clip to a full-frame PNG using its normalised position box."""
    pos = position or {"x": 0.5, "y": 0.15, "w": 0.8, "h": 0.1}
    cs = CaptionStyle(
        font=str(style.get("font", "Inter")),
        font_size=int(style.get("font_size", 48)),
        color=str(style.get("color", "#FFFFFF")),
        outline=float(style.get("outline", 2.0)),
        shadow=float(style.get("shadow", 1.0)),
        background=style.get("background"),
        alignment=str(style.get("alignment", "center")),
        uppercase=bool(style.get("uppercase", False)),
    )  # type: ignore[arg-type]
    size = max(12, int(cs.font_size * height / 1080))
    font = _load_font(cs, size)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    words = text.upper().split() if cs.uppercase else text.split()
    box_w = int(pos["w"] * width)
    lines = _wrap(draw, words, font, box_w)
    line_h = int(size * 1.25)
    y = int(pos["y"] * height - (line_h * len(lines)) / 2)
    cx0 = int((pos["x"] - pos["w"] / 2) * width)
    for ln in lines:
        line = " ".join(words[i] for i in ln)
        lw = draw.textlength(line, font=font)
        x = {"left": cx0, "center": int(cx0 + (box_w - lw) / 2), "right": int(cx0 + box_w - lw)}[
            cs.alignment
        ]
        if cs.shadow > 0:
            draw.text(
                (x + 2, y + 2),
                line,
                font=font,
                fill=(0, 0, 0, 170),
                stroke_width=int(cs.outline),
                stroke_fill=(0, 0, 0, 170),
            )
        draw.text(
            (x, y),
            line,
            font=font,
            fill=_hex_rgba(cs.color, (255, 255, 255, 255)),
            stroke_width=int(cs.outline),
            stroke_fill=_hex_rgba(cs.outline_color, (0, 0, 0, 255)),
        )
        y += line_h
    img.save(out, "PNG", compress_level=1)
    return out


def write_concat_list(
    items: list[RasterCue], total_duration: float, blank: Path, out: Path, *, min_step: float = 0.02
) -> Path:
    """Concat-demuxer playlist turning timed PNGs into one sparse overlay stream (transparent gaps)."""
    lines = ["ffconcat version 1.0"]
    t = 0.0

    def add(path: Path, dur: float) -> None:
        nonlocal t
        if dur <= 0:
            return
        lines.append(f"file '{path.as_posix()}'")
        lines.append(f"duration {dur:.3f}")
        t += dur

    for item in sorted(items, key=lambda i: i.start):
        if item.start > t + min_step:
            add(blank, item.start - t)
        end = max(item.end, item.start + min_step)
        if end > t:
            add(item.path, end - max(t, item.start))
    if total_duration > t:
        add(blank, total_duration - t)
    # concat demuxer needs the last file repeated to honour its duration
    lines.append(f"file '{blank.as_posix()}'")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def blank_image(width: int, height: int, out: Path) -> Path:
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(out, "PNG", compress_level=1)
    return out


def ceil_even(v: float) -> int:
    return int(math.ceil(v / 2) * 2)
