"""Timeline document → FFmpeg command compiler.

Deterministic: the same document, sources and preset always produce the same filter graph.
Everything the LLM decided is already in the document; nothing here consults a model.

Video: per-clip trim/speed/effects → fit to canvas → concat (with fades / handle-based crossfades)
→ optional reframe crop driven by `sendcmd` keyframes → overlays (B-roll, images, text) → captions
(rasterised PNG cue stream) → encoder.
Audio: per-clip trim/tempo/gain/fades/effects → dialogue mix → music ducked by sidechain compression
→ global loudness/noise processing → encoder.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path

from cutpilot.core.config import get_settings
from cutpilot.core.errors import MediaProcessingError
from cutpilot.render.captions import (
    Cue,
    blank_image,
    caption_cues,
    ceil_even,
    rasterize_cues,
    render_text_overlay_image,
    write_concat_list,
)
from cutpilot.render.presets import ExportPreset
from cutpilot.timeline.model import Clip, Effect, TimelineDocument, Track

_X264_PRESETS = [
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
]


def encoder_preset(preset: str) -> str:
    """In low-memory mode never go slower than `veryfast`: slower x264 presets use bigger
    lookahead/reference buffers, which is what pushes a 512 MB container over the edge."""
    if not get_settings().ffmpeg_low_memory or preset not in _X264_PRESETS:
        return preset
    return preset if _X264_PRESETS.index(preset) <= _X264_PRESETS.index("veryfast") else "veryfast"


@dataclass
class SourceMedia:
    asset_id: str
    path: Path
    duration: float
    width: int | None = None
    height: int | None = None
    has_video: bool = True
    has_audio: bool = True
    is_image: bool = False


@dataclass
class RenderPlan:
    args: list[str]
    output: Path
    duration: float
    filter_script: Path
    aux_files: list[Path] = field(default_factory=list)
    width: int = 0
    height: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def command(self) -> str:
        import shlex

        return "ffmpeg " + " ".join(shlex.quote(a) for a in self.args)


class CompileError(MediaProcessingError):
    """Non-retryable: the document itself cannot be rendered."""


def _f(v: float) -> str:
    return f"{v:.4f}"


def _esc(path: Path) -> str:
    """Escape a path for use inside a filter option value."""
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


class Compiler:
    def __init__(
        self,
        doc: TimelineDocument,
        sources: dict[str, SourceMedia],
        preset: ExportPreset,
        output: Path,
        work: Path,
    ):
        self.doc = doc
        self.sources = sources
        self.preset = preset
        self.output = output
        self.work = work
        self.work.mkdir(parents=True, exist_ok=True)
        self.inputs: list[list[str]] = []  # per input: args before path + path
        self.input_index: dict[str, int] = {}
        self.filters: list[str] = []
        self.aux: list[Path] = []
        self.companion_ids: set[str] = set()  # audio clips carried with the video stream
        self.warnings: list[str] = []
        self._label = 0
        self.W, self.H = preset.width, preset.height
        self.fps = float(preset.fps or doc.settings.fps or 30.0)
        self.reframe = doc.settings.reframe if doc.settings.reframe else None
        self.duration = doc.duration()
        if self.duration <= 0:
            raise CompileError("Timeline is empty")
        # Intermediate canvas for reframe mode: keep source aspect (height-fit), crop later.
        self.IW = self.W
        if self.reframe:
            widest = self.W
            for src in sources.values():
                if src.has_video and src.width and src.height:
                    widest = max(widest, ceil_even(self.H * src.width / src.height))
            self.IW = widest

    # ── helpers ────────────────────────────────────────────────────────────
    def label(self, prefix: str = "v") -> str:
        self._label += 1
        return f"{prefix}{self._label}"

    def add_input(self, key: str, args: list[str]) -> int:
        if key in self.input_index:
            return self.input_index[key]
        idx = len(self.inputs)
        self.inputs.append(args)
        self.input_index[key] = idx
        return idx

    def source_input(self, asset_id: str) -> int:
        src = self.sources.get(asset_id)
        if src is None:
            raise CompileError(f"asset {asset_id} is not available for rendering")
        return self.add_input(f"asset:{asset_id}", ["-i", str(src.path)])

    def image_input(self, path: Path, duration: float) -> int:
        return self.add_input(
            f"img:{path}:{duration:.3f}",
            ["-loop", "1", "-framerate", _f(self.fps), "-t", _f(duration + 0.5), "-i", str(path)],
        )

    # ── video ──────────────────────────────────────────────────────────────
    def fit_filter(self) -> str:
        if self.reframe:
            return f"scale=-2:{self.H},crop='min(iw,{self.IW})':{self.H},pad={self.IW}:{self.H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        return f"scale={self.W}:{self.H}:force_original_aspect_ratio=decrease,pad={self.W}:{self.H}:(ow-iw)/2:(oh-ih)/2,setsar=1"

    def canvas(self) -> tuple[int, int]:
        return (self.IW, self.H) if self.reframe else (self.W, self.H)

    def effect_filters(self, clip: Clip, seg_duration: float) -> list[str]:
        """Per-clip visual effects, applied on the fitted canvas (times relative to segment start)."""
        out: list[str] = []
        cw, ch = self.canvas()
        zooms = [fx for fx in clip.effects if fx.type == "zoom" and fx.enabled]
        for fx in clip.effects:
            if not fx.enabled:
                continue
            en = self._enable(fx, seg_duration)
            p = fx.params
            if fx.type == "crop":
                x, y, w, h = (
                    float(p.get(k, d)) for k, d in (("x", 0.0), ("y", 0.0), ("w", 1.0), ("h", 1.0))
                )
                out.append(
                    f"crop=w=iw*{_f(w)}:h=ih*{_f(h)}:x=iw*{_f(x)}:y=ih*{_f(y)},scale={cw}:{ch}:force_original_aspect_ratio=decrease,pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2"
                )
            elif fx.type == "stabilization":
                out.append("deshake=rx=32:ry=32")
            elif fx.type == "color_adjustment":
                eq = ":".join(
                    f"{k}={_f(float(p[k]))}"
                    for k in ("brightness", "contrast", "saturation", "gamma")
                    if k in p
                )
                if eq:
                    out.append(f"eq={eq}{en}")
            elif fx.type == "lut" and p.get("file"):
                out.append(f"lut3d=file='{_esc(Path(str(p['file'])))}'{en}")
            elif fx.type in ("blur",):
                out.append(f"boxblur={int(p.get('radius', 10))}{en}")
            elif fx.type in ("object_blur", "face_blur"):
                for r in p.get("regions", []) or []:
                    rx, ry, rw, rh = (float(r.get(k, 0.0)) for k in ("x", "y", "w", "h"))
                    a, b = float(r.get("start", 0.0)), float(r.get("end", seg_duration))
                    out.append(
                        f"split[bm][bb];[bb]crop=w=iw*{_f(rw)}:h=ih*{_f(rh)}:x=iw*{_f(rx)}:y=ih*{_f(ry)},boxblur=20[bblur];[bm][bblur]overlay=x=W*{_f(rx)}:y=H*{_f(ry)}:enable='between(t,{_f(a)},{_f(b)})'"
                    )
            elif fx.type == "fade_video":
                d = float(p.get("duration", 1.0))
                if p.get("position", "out") == "in":
                    out.append(f"fade=t=in:st=0:d={_f(d)}")
                else:
                    out.append(f"fade=t=out:st={_f(max(0.0, seg_duration - d))}:d={_f(d)}")
        if zooms:
            terms = []
            for fx in zooms:
                s = float(fx.params.get("scale", 1.12))
                t0 = float(fx.start or 0.0)
                d = float(fx.duration or (seg_duration - t0))
                r = max(0.1, min(0.4, d / 3))
                terms.append(
                    f"({_f(s - 1)})*clip(min((t-{_f(t0)})/{_f(r)},({_f(t0 + d)}-t)/{_f(r)}),0,1)"
                )
            z = "1+" + "+".join(terms)
            ax = float(zooms[0].params.get("x", 0.5))
            ay = float(zooms[0].params.get("y", 0.5))
            out.append(
                f"scale=w='2*trunc(iw*({z})/2)':h='2*trunc(ih*({z})/2)':eval=frame,crop={cw}:{ch}:x='(iw-{cw})*{_f(ax)}':y='(ih-{ch})*{_f(ay)}'"
            )
        return out

    @staticmethod
    def _enable(fx: Effect, seg_duration: float) -> str:
        if fx.start is None and fx.duration is None:
            return ""
        s = float(fx.start or 0.0)
        e = s + float(fx.duration if fx.duration is not None else seg_duration - s)
        return f":enable='between(t,{_f(s)},{_f(e)})'"

    def video_segment(
        self, clip: Clip, *, head_extend: float = 0.0, tail_extend: float = 0.0
    ) -> tuple[str, str, float]:
        """Return (video label, audio label, duration) of a fitted primary-track segment.

        Video and audio are produced as a *pair* and later joined with a single
        `concat=v=1:a=1`, so ffmpeg advances both in lockstep. Placing audio with adelay/apad
        instead forces the demuxer to read the whole source ahead, and every decoded video frame
        of the later clips piles up in the concat inputs (713 MB vs ~200 MB for a 30 s render).
        """
        src = self.sources.get(clip.asset_id or "")
        if src is None:
            return self.gap_segment(clip.duration)
        si = max(0.0, clip.source_in - head_extend * clip.speed)
        so = min(
            src.duration if src.duration > 0 else clip.source_out,
            clip.source_out + tail_extend * clip.speed,
        )
        seg_dur = clip.duration + head_extend + tail_extend if not src.is_image else clip.duration
        lab = self.label()
        chain: list[str]
        if src.is_image or not src.has_video:
            idx = self.image_input(src.path, seg_dur) if src.is_image else None
            if idx is None:
                return self.gap_segment(clip.duration)
            chain = [
                f"[{idx}:v]",
                f"fps={_f(self.fps)}",
                self.fit_filter(),
                f"trim=0:{_f(seg_dur)}",
                "setpts=PTS-STARTPTS",
            ]
        else:
            idx = self.source_input(clip.asset_id or "")
            chain = [
                f"[{idx}:v]",
                f"trim=start={_f(si)}:end={_f(so)}",
                f"setpts=(PTS-STARTPTS)/{_f(clip.speed)}",
                f"fps={_f(self.fps)}",
                self.fit_filter(),
            ]
        chain += self.effect_filters(clip, seg_dur)
        chain.append("format=yuv420p")
        self.filters.append(chain[0] + ",".join(chain[1:]) + f"[{lab}]")
        return lab, self.companion_audio(clip, si, so, seg_dur), seg_dur

    def linked_audio(self, clip: Clip) -> Clip | None:
        """The audio clip paired with a primary-track video clip (either side may hold the link)."""
        for track in self.doc.tracks_of_kind("audio"):
            for c in track.clips:
                if c.id == clip.linked_clip_id or (c.linked_clip_id == clip.id and c.id):
                    return None if track.muted else c
        return None

    def companion_audio(self, clip: Clip, si: float, so: float, seg_dur: float) -> str:
        """Audio segment that travels with a video segment: the linked audio clip's processing over
        the same source range, or exact-length silence when there is none (or it is muted)."""
        audio = self.linked_audio(clip)
        src = self.sources.get(clip.asset_id or "")
        if audio is None or audio.muted or src is None or not src.has_audio:
            return self.silence_segment(seg_dur)
        self.companion_ids.add(audio.id)
        idx = self.source_input(clip.asset_id or "")
        chain = [f"atrim=start={_f(si)}:end={_f(so)}", *self._audio_chain(audio, seg_dur)]
        chain += [f"apad=whole_dur={_f(seg_dur)}", f"atrim=0:{_f(seg_dur)}"]
        lab = self.label("a")
        self.filters.append(f"[{idx}:a]" + ",".join(chain) + f"[{lab}]")
        return lab

    def silence_segment(self, duration: float) -> str:
        lab = self.label("a")
        self.filters.append(
            f"anullsrc=r=48000:cl=stereo,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{_f(duration)}[{lab}]"
        )
        return lab

    def gap_segment(self, duration: float) -> tuple[str, str, float]:
        cw, ch = self.canvas()
        lab = self.label()
        self.filters.append(
            f"color=c={self.doc.settings.background}:s={cw}x{ch}:r={_f(self.fps)}:d={_f(duration)},format=yuv420p[{lab}]"
        )
        return lab, self.silence_segment(duration), duration

    def build_base_video(self) -> tuple[str, str]:
        """Primary video track → one video stream and its lockstep audio, gaps filled,
        transitions applied. Returns (video label, audio label)."""
        track = self.doc.primary_video_track()
        clips = [c for c in track.sorted_clips() if not track.hidden]
        segments: list[tuple[str, str, float, Clip | None]] = []
        t = 0.0
        # Crossfade handle allocation: consecutive clips each give half the transition from their handles.
        for i, clip in enumerate(clips):
            if clip.timeline_start > t + 0.001:
                segments.append((*self.gap_segment(clip.timeline_start - t), None))
            prev = clips[i - 1] if i > 0 else None
            nxt = clips[i + 1] if i + 1 < len(clips) else None
            head = tail = 0.0
            if prev is not None and self._xfade_ok(prev, clip):
                head = prev.transition_out.duration / 2
            if nxt is not None and self._xfade_ok(clip, nxt):
                tail = clip.transition_out.duration / 2
            vlab, alab, dur = self.video_segment(clip, head_extend=head, tail_extend=tail)
            segments.append((vlab, alab, dur, clip))
            t = clip.timeline_end
        if not segments:
            raise CompileError("No video clips on the primary track")
        # Combine: runs joined by a paired concat, crossfades via xfade + acrossfade, dips via fades.
        acc_v, acc_a, acc_dur, _ = segments[0]
        pending: list[tuple[str, str]] = [(acc_v, acc_a)]
        pending_dur = acc_dur

        def flush_concat() -> None:
            nonlocal acc_v, acc_a, pending
            if len(pending) > 1:
                v, a = self.label(), self.label("a")
                self.filters.append(
                    "".join(f"[{pv}][{pa}]" for pv, pa in pending)
                    + f"concat=n={len(pending)}:v=1:a=1[{v}][{a}]"
                )
                acc_v, acc_a = v, a
            else:
                acc_v, acc_a = pending[0]

        for i in range(1, len(segments)):
            prev_clip = segments[i - 1][3]
            vlab, alab, dur, clip = segments[i]
            if prev_clip is not None and clip is not None and self._xfade_ok(prev_clip, clip):
                flush_concat()
                d = prev_clip.transition_out.duration
                v, a = self.label(), self.label("a")
                self.filters.append(
                    f"[{acc_v}][{vlab}]xfade=transition=fade:duration={_f(d)}:offset={_f(pending_dur - d)}[{v}]"
                )
                self.filters.append(f"[{acc_a}][{alab}]acrossfade=d={_f(d)}:c1=tri:c2=tri[{a}]")
                pending = [(v, a)]
                pending_dur = pending_dur + dur - d
                continue
            if (
                prev_clip is not None
                and prev_clip.transition_out.type in ("fade_black", "dip_to_white")
                and prev_clip.transition_out.duration > 0
            ):
                d = prev_clip.transition_out.duration / 2
                color = "white" if prev_clip.transition_out.type == "dip_to_white" else "black"
                fa, fb = self.label(), self.label()
                pv, pa = pending[-1]
                self.filters.append(
                    f"[{pv}]fade=t=out:st={_f(max(0.0, segments[i - 1][2] - d))}:d={_f(d)}:color={color}[{fa}]"
                )
                pending[-1] = (fa, pa)
                self.filters.append(f"[{vlab}]fade=t=in:st=0:d={_f(d)}:color={color}[{fb}]")
                vlab = fb
            pending.append((vlab, alab))
            pending_dur += dur
        flush_concat()
        return acc_v, acc_a

    def _xfade_ok(self, a: Clip, b: Clip) -> bool:
        """Crossfade needs media handles on both sides so the timeline duration is preserved."""
        if a.transition_out.type != "crossfade" or a.transition_out.duration <= 0:
            return False
        d = a.transition_out.duration / 2
        sa, sb = self.sources.get(a.asset_id or ""), self.sources.get(b.asset_id or "")
        if not sa or not sb or sa.is_image or sb.is_image:
            return False
        if abs(a.timeline_end - b.timeline_start) > 0.01:
            return False
        if a.source_out + d * a.speed > sa.duration + 0.001 or b.source_in - d * b.speed < -0.001:
            self.warnings.append(
                f"crossfade between {a.name} and {b.name} needs {d:.2f}s handles; rendered as a cut"
            )
            return False
        return True

    def apply_reframe(self, base: str) -> str:
        if not self.reframe or self.IW == self.W:
            return base
        keyframes = sorted(
            (
                {"t": float(k.get("t", 0.0)), "x": float(k.get("x", 0.5))}
                for k in (self.reframe.get("keyframes") or [])
            ),
            key=lambda k: k["t"],
        )
        mode = self.reframe.get("mode", "center")
        span = self.IW - self.W
        cmd_path = self.work / "reframe_cmds.txt"
        lines: list[str] = []
        if mode == "track" and len(keyframes) >= 2:
            for a, b in itertools.pairwise(keyframes):
                if b["t"] <= a["t"]:
                    continue
                xa, xb = span * min(1.0, max(0.0, a["x"])), span * min(1.0, max(0.0, b["x"]))
                lines.append(
                    f"{_f(a['t'])}-{_f(b['t'])} [expr] crop@reframe x 'lerp({_f(xa)},{_f(xb)},TI)';"
                )
            last = keyframes[-1]
            lines.append(
                f"{_f(last['t'])}-{_f(self.duration + 1)} [expr] crop@reframe x '{_f(span * last['x'])}';"
            )
            x0 = span * keyframes[0]["x"]
        else:
            x = span * (keyframes[0]["x"] if keyframes else 0.5)
            x0 = x
        out = self.label()
        if lines:
            cmd_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.aux.append(cmd_path)
            self.filters.append(
                f"[{base}]sendcmd=f='{_esc(cmd_path)}',crop@reframe={self.W}:{self.H}:x={_f(x0)}:y=0[{out}]"
            )
        else:
            self.filters.append(f"[{base}]crop={self.W}:{self.H}:x={_f(x0)}:y=0[{out}]")
        return out

    def apply_overlays(self, base: str) -> str:
        acc = base
        video_tracks = self.doc.tracks_of_kind("video")[1:]
        overlay_tracks = self.doc.tracks_of_kind("overlay")
        for track in [*video_tracks, *overlay_tracks]:
            if track.hidden:
                continue
            for clip in track.sorted_clips():
                acc = self.overlay_clip(acc, clip, track)
        return acc

    def overlay_clip(self, acc: str, clip: Clip, track: Track) -> str:
        ts, te = clip.timeline_start, clip.timeline_end
        ov = self.label("o")
        if clip.kind == "text" and clip.text:
            png = self.work / f"text_{clip.id}.png"
            render_text_overlay_image(clip.text, clip.style, self.W, self.H, clip.position, png)
            self.aux.append(png)
            idx = self.image_input(png, clip.duration)
            self.filters.append(f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS+{_f(ts)}/TB[{ov}]")
            pos = "0:0"
        else:
            src = self.sources.get(clip.asset_id or "")
            if src is None:
                return acc  # B-roll suggestion without media: nothing to render
            if clip.position:
                w = ceil_even(clip.position["w"] * self.W)
                h = ceil_even(clip.position["h"] * self.H)
                x = int(clip.position["x"] * self.W - w / 2)
                y = int(clip.position["y"] * self.H - h / 2)
                fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease"
                pos = f"{x}:{y}"
            else:
                fit = f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H}"
                pos = "0:0"
            if src.is_image:
                idx = self.image_input(src.path, clip.duration)
                self.filters.append(
                    f"[{idx}:v]fps={_f(self.fps)},{fit},format=rgba,setpts=PTS-STARTPTS+{_f(ts)}/TB[{ov}]"
                )
            else:
                idx = self.source_input(clip.asset_id or "")
                chain = [
                    f"trim=start={_f(clip.source_in)}:end={_f(clip.source_out)}",
                    f"setpts=(PTS-STARTPTS)/{_f(clip.speed)}",
                    f"fps={_f(self.fps)}",
                    fit,
                ]
                chain += self.effect_filters(clip, clip.duration)
                chain += ["format=yuv420p", f"setpts=PTS+{_f(ts)}/TB"]
                self.filters.append(f"[{idx}:v]" + ",".join(chain) + f"[{ov}]")
        out = self.label()
        fade = ""
        if clip.transition_in.type != "cut" and clip.transition_in.duration > 0:
            fade = f"fade=t=in:st={_f(ts)}:d={_f(clip.transition_in.duration)}:alpha=1,"
        if fade:
            self.filters.append(f"[{ov}]{fade[:-1]}[{ov}f]")
            ov = f"{ov}f"
        self.filters.append(
            f"[{acc}][{ov}]overlay={pos}:eof_action=pass:enable='between(t,{_f(ts)},{_f(te)})'[{out}]"
        )
        return out

    def apply_captions(self, acc: str) -> str:
        cues: list[Cue] = caption_cues(self.doc)
        if not cues:
            return acc
        raster = rasterize_cues(
            cues, self.doc.settings.caption_style, self.W, self.H, self.work / "captions"
        )
        blank = blank_image(self.W, self.H, self.work / "captions" / "blank.png")
        playlist = write_concat_list(
            raster, self.duration, blank, self.work / "captions" / "cues.ffconcat"
        )
        self.aux.extend([blank, playlist, *(r.path for r in raster)])
        idx = self.add_input("captions", ["-f", "concat", "-safe", "0", "-i", str(playlist)])
        cap, out = self.label("c"), self.label()
        self.filters.append(f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS[{cap}]")
        self.filters.append(f"[{acc}][{cap}]overlay=0:0:eof_action=pass:format=auto[{out}]")
        return out

    # ── audio ──────────────────────────────────────────────────────────────
    def _audio_chain(self, clip: Clip, seg_dur: float) -> list[str]:
        """Per-clip audio processing (format, loop, tempo, effects, gain, fades) — no placement."""
        chain = [
            "asetpts=PTS-STARTPTS",
            "aresample=48000",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
        ]
        if clip.loop:
            samples = int(max(1.0, clip.source_out - clip.source_in) * 48000)
            chain += [
                f"aloop=loop=-1:size={min(samples, 2_000_000_000)}",
                f"atrim=0:{_f(seg_dur)}",
                "asetpts=PTS-STARTPTS",
            ]
        chain += self._atempo(clip.speed)
        for fx in clip.effects:
            if not fx.enabled:
                continue
            en = self._enable(fx, seg_dur)
            if fx.type == "audio_gain":
                chain.append(f"volume={_f(float(fx.params.get('gain_db', 0.0)))}dB{en}")
            elif fx.type == "noise_reduction":
                chain.append(f"afftdn=nf={int(fx.params.get('noise_floor_db', -25))}{en}")
            elif fx.type == "voice_enhancement":
                chain.append(
                    f"highpass=f=90{en},lowpass=f=14000{en},speechnorm=e=4:r=0.0005:l=1{en}"
                )
            elif fx.type == "normalize_audio":
                chain.append("dynaudnorm=f=150:g=15")
        if clip.gain_db:
            chain.append(f"volume={_f(clip.gain_db)}dB")
        if clip.fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={_f(clip.fade_in)}")
        if clip.fade_out > 0:
            chain.append(
                f"afade=t=out:st={_f(max(0.0, seg_dur - clip.fade_out))}:d={_f(clip.fade_out)}"
            )
        return chain

    def audio_clip(self, clip: Clip) -> str | None:
        """A free-standing audio clip (music, voice-over, unlinked dialogue) placed on the
        timeline with adelay/apad. Linked dialogue never comes through here — see companion_audio."""
        src = self.sources.get(clip.asset_id or "")
        if src is None or not src.has_audio or clip.muted:
            return None
        idx = self.source_input(clip.asset_id or "")
        lab = self.label("a")
        chain = [
            f"atrim=start={_f(clip.source_in)}:end={_f(clip.source_out)}",
            *self._audio_chain(clip, clip.duration),
            f"atrim=0:{_f(clip.duration)}",
            f"adelay={round(clip.timeline_start * 1000)}:all=1",
            f"apad=whole_dur={_f(self.duration)}",
            f"atrim=0:{_f(self.duration)}",
        ]
        self.filters.append(f"[{idx}:a]" + ",".join(chain) + f"[{lab}]")
        return lab

    @staticmethod
    def _atempo(speed: float) -> list[str]:
        if abs(speed - 1.0) < 1e-6:
            return []
        out: list[str] = []
        s = speed
        while s > 2.0:
            out.append("atempo=2.0")
            s /= 2.0
        while s < 0.5:
            out.append("atempo=0.5")
            s /= 0.5
        out.append(f"atempo={_f(s)}")
        return out

    def build_audio(self, base_audio: str) -> str:
        dialogue: list[str] = [base_audio]
        ducked: list[str] = []
        plain_music: list[str] = []
        for track in self.doc.tracks_of_kind("audio"):
            if track.muted:
                continue
            for clip in track.sorted_clips():
                if clip.id in self.companion_ids:
                    continue  # already carried by the primary video stream
                lab = self.audio_clip(clip)
                if lab is None:
                    continue
                if clip.ducking:
                    ducked.append(lab)
                elif clip.kind == "music":
                    plain_music.append(lab)
                else:
                    dialogue.append(lab)
        dlg = self._amix(dialogue)
        g = self.doc.settings.audio or {}
        if (
            g.get("noise_reduction", {}).get("enabled")
            if isinstance(g.get("noise_reduction"), dict)
            else g.get("noise_reduction")
        ):
            nd = self.label("a")
            self.filters.append(f"[{dlg}]afftdn=nf=-25[{nd}]")
            dlg = nd
        if (
            g.get("voice_enhancement", {}).get("enabled")
            if isinstance(g.get("voice_enhancement"), dict)
            else g.get("voice_enhancement")
        ):
            ve = self.label("a")
            self.filters.append(
                f"[{dlg}]highpass=f=90,lowpass=f=14000,speechnorm=e=4:r=0.0005:l=1[{ve}]"
            )
            dlg = ve
        mix_inputs = [dlg, *plain_music]
        if ducked:
            side = self.label("a")
            self.filters.append(f"[{dlg}]asplit=2[{dlg}m][{side}]")
            dlg = f"{dlg}m"
            mix_inputs[0] = dlg
            music = self._amix(ducked) if len(ducked) > 1 else ducked[0]
            dk = self.label("a")
            self.filters.append(
                f"[{music}][{side}]sidechaincompress=threshold=0.02:ratio=8:attack=120:release=900:makeup=1[{dk}]"
            )
            mix_inputs.append(dk)
        mixed = self._amix(mix_inputs)
        if (
            g.get("normalize_audio", {}).get("enabled")
            if isinstance(g.get("normalize_audio"), dict)
            else g.get("normalize_audio")
        ):
            ln = self.label("a")
            self.filters.append(f"[{mixed}]loudnorm=I=-16:TP=-1.5:LRA=11[{ln}]")
            mixed = ln
        out = "aout"
        self.filters.append(
            f"[{mixed}]apad=whole_dur={_f(self.duration)},atrim=0:{_f(self.duration)},"
            f"asetpts=PTS-STARTPTS,aresample=48000[{out}]"
        )
        return out

    def _amix(self, labels: list[str]) -> str:
        if len(labels) == 1:
            return labels[0]
        out = self.label("a")
        self.filters.append(
            "".join(f"[{lab}]" for lab in labels)
            + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[{out}]"
        )
        return out

    # ── assemble ───────────────────────────────────────────────────────────
    def compile(self) -> RenderPlan:
        base, base_audio = self.build_base_video()
        base = self.apply_reframe(base)
        base = self.apply_overlays(base)
        base = self.apply_captions(base)
        self.filters.append(
            f"[{base}]trim=0:{_f(self.duration)},setpts=PTS-STARTPTS,format=yuv420p[vout]"
        )
        aout = self.build_audio(base_audio)
        script = self.work / "filter_complex.txt"
        script.write_text(";\n".join(self.filters) + "\n", encoding="utf-8")
        p = self.preset
        args: list[str] = []
        for inp in self.inputs:
            args += inp
        args += ["-filter_complex_script", str(script), "-map", "[vout]", "-map", f"[{aout}]"]
        args += [
            "-c:v",
            p.codec,
            "-preset",
            encoder_preset(p.preset),
            "-crf",
            str(p.crf),
            "-maxrate",
            p.video_bitrate,
            "-bufsize",
            _bufsize(p.video_bitrate),
            "-r",
            _f(self.fps),
            "-pix_fmt",
            "yuv420p",
        ]
        if p.codec == "libx264":
            args += ["-profile:v", "high", "-level", "4.2" if self.H <= 1080 else "5.1"]
        args += [
            "-c:a",
            "aac",
            "-b:a",
            p.audio_bitrate,
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-t",
            _f(self.duration),
            str(self.output),
        ]
        return RenderPlan(
            args=args,
            output=self.output,
            duration=self.duration,
            filter_script=script,
            aux_files=list(self.aux),
            width=self.W,
            height=self.H,
            warnings=self.warnings,
        )


def _bufsize(bitrate: str) -> str:
    unit = bitrate[-1].lower()
    num = float(bitrate[:-1]) if unit in ("k", "m") else float(bitrate) / 1000
    if unit == "m":
        num *= 1000
    return f"{int(num * 2)}k"


def compile_timeline(
    doc: TimelineDocument,
    sources: dict[str, SourceMedia],
    preset: ExportPreset,
    output: Path,
    work: Path,
) -> RenderPlan:
    return Compiler(doc, sources, preset, output, work).compile()
