# Timeline

## Document model (`cutpilot/timeline/model.py`)

```
TimelineDocument
  settings: width, height, fps, aspect_ratio, caption_style, audio{…}, reframe{mode, keyframes}
  tracks[]: id, kind (video|audio|caption|overlay), name, index, muted, locked, hidden, clips[]
    Clip: id, kind (video|audio|image|caption|text|broll|music), asset_id, timeline_start, duration,
          source_in, source_out, speed, gain_db, muted, text, words[], style, position, effects[],
          transition_in/out, linked_clip_id, loop, fade_in, fade_out, ducking
    Effect: type (zoom|crop|reframe|fade_video|fade_audio|audio_gain|noise_reduction|…), start, duration, params
  markers[]: time, label, kind (marker|chapter|broll_suggestion)
```
Time model: `source = source_in + (t - timeline_start) * speed`. Media referenced by `asset_id` is immutable.
A default sequence has V1, V2, A1, A2 and a Captions track; overlay tracks are created on demand.

## Operations (`cutpilot/timeline/operations.py`)

`EditOperation` is the strict schema for every edit (AI or user): `id, type, asset_id|source_clip_id,
track_id, time_ref (source|timeline), start/end/timestamp/duration, segments[], params, text, query,
scale, confidence, reason, source (ai|user|system), reversible`. Supported types: cut, split, trim,
remove_segment, delete_clip, merge, reorder, move_clip, speed_change, jump_cut, transition, zoom, crop,
reframe, caption, subtitle, text_overlay, image_overlay, insert_broll, insert_image, insert_audio, music,
audio_gain, mute, noise_reduction, voice_enhancement, normalize_audio, fade_audio, fade_video, blur,
object_blur, face_blur, color_adjustment, brightness, contrast, saturation, lut, stabilization,
filler_word_removal, silence_removal, set_track_state, add_marker.

## Engine (`cutpilot/timeline/engine.py`)

`apply_operations(doc, ops)` returns a **new** document plus applied/rejected lists; an invalid op is
rolled back individually. Source-time ranges are mapped onto every clip that uses the asset; removals
ripple across all tracks; splits re-pair linked audio/video pieces; captions map through video tracks and
are clamped so they never stack. `add_source_clip` appends footage with linked audio.

## Versions

Every change creates a `TimelineVersion` (immutable JSON snapshot, `parent_version_id`, `source`, label,
duration). `Timeline.current_version_id` is the pointer: undo = parent, redo = newest child, restore =
new version copying an old document, compare = clip-level diff. AI proposals are applied as `ai` versions
with their `edit_operations` recorded.

## Web editor (`apps/web/components/timeline`, `lib/timeline-engine.ts`)

A client-side mirror of the time math drives the timeline UI (drag/trim/snap), the player composition
(`playbackAt`) and Descript-style transcript editing (word selection → `remove_segment` in source time).
Drag/trim edits mutate a local copy and are saved as a version on drop; structural edits go through the
operations endpoint. Preview mode renders a proposed document read-only with cut overlays.
