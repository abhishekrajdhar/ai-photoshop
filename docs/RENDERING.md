# Rendering

`cutpilot/render/compiler.py` turns a `TimelineDocument` into one FFmpeg invocation
(`-filter_complex_script`), deterministically.

## Video

1. **Primary track** — each clip: `trim` (source range) → `setpts` (speed) → `fps` → fit to canvas
   (letterbox, or height-fit onto a wide intermediate canvas in reframe mode) → per-clip effects → `format`.
   Gaps become `color` sources. Effects: `crop`, `deshake`, `eq`, `lut3d`, `boxblur`, region blur
   (split/crop/blur/overlay with `enable`), `fade`; **zoom** = `scale` with `eval=frame` time expression
   (ease-in/hold/ease-out) + centred `crop`.
2. **Transitions** — `fade_black`/`dip_to_white` as symmetric fades (no timing change); `crossfade` as
   `xfade` fed with media *handles* from both clips so the sequence duration is preserved (falls back to a
   cut with a warning when handles are missing).
3. **Concat** of runs, then **reframe**: `sendcmd` with `[expr] crop@reframe x 'lerp(...)'` intervals from
   face-tracking keyframes (`render/reframe_keys.py`) → `crop@reframe=W:H`.
4. **Overlays** — B-roll/video/image clips and text overlays (rasterised with Pillow) via `overlay` with
   `enable='between(t,…)'`, positioned from normalised boxes.
5. **Captions** — cues rasterised to transparent PNGs (`render/captions.py`, presets clean/bold/karaoke/
   minimal/boxed, karaoke/word highlight = one image per word interval) and fed as **one** overlay stream
   through the concat demuxer (`cues.ffconcat`). This avoids a libass dependency and renders identically
   on every FFmpeg build.

## Audio

Per clip: `atrim` → `aresample`/`aformat` → optional `aloop` (music) → `atempo` chain → per-clip effects
(`volume`, `afftdn`, `highpass/lowpass/speechnorm`, `dynaudnorm`) → gain → `afade` in/out → `adelay` →
`apad`. Dialogue clips are summed (`amix normalize=0`), music with `ducking` passes through
`sidechaincompress` keyed by the dialogue mix, global `afftdn` / voice enhancement / `loudnorm` from
`settings.audio`, and an `anullsrc` bed guarantees an audio stream.

## Encoding & presets

`render/presets.py`: YouTube 1080p/4K, Instagram Reel, TikTok, YouTube Shorts, Podcast, Preview (draft),
Custom (width/height/fps/bitrate/codec). H.264 (`libx264`, CRF + maxrate), H.265, VP9; AAC 48 kHz;
`+faststart`.

## Exports

- Captions: SRT, WebVTT, ASS (karaoke tags).
- OpenTimelineIO JSON (tracks, clips with external references, gaps, time warps, markers).
- CMX3600 EDL (primary video track), FCPXML 1.9 (spine + connected clips + titles).

## Jobs

`RENDERING` / `EXPORT` run on the `render` queue with progress parsed from `-progress pipe:1`, cancellable,
retried once. Outputs are stored as `render` / `export` assets with ffprobe metadata; the render row keeps
the exact FFmpeg command for debugging.

## Verified test case

`tests/test_render.py::test_spec_render_case_produces_valid_mp4`: 60 s talking head → remove 5–8 s and
17–20 s, caption 21–25 s, zoom 1.1× 30–33 s, music at −22 dB (looped, ducked), reframe 9:16 with tracking
keyframes → valid 54 s H.264/AAC 9:16 MP4.
