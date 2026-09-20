# AI pipeline

## Provider abstraction

`cutpilot/ai/providers/base.py` defines `LLMProvider.complete(messages, system, json_schema, tools, …)`
returning text, parsed JSON and tool calls. Implementations: `OpenAIProvider` (chat completions,
`json_object` mode, function tools, `image_url` inputs) and `AnthropicProvider` (messages API, forced tool
call for structured output, tool use, base64 images).

`cutpilot/ai/router.py`:
- `available_providers()` — preferred (`AI_PROVIDER`) → fallback (`AI_FALLBACK_PROVIDER`) → any configured.
- `AIRouter.complete()` — tries providers in order, logs usage (tokens, latency, estimated cost) to
  `ai_requests`, falls back on provider errors.
- `AIRouter.complete_structured(Model)` — validate with Pydantic → on failure feed the errors back for a
  repair turn (configurable attempts) → raise `AIProviderError` if still invalid. **No unvalidated JSON
  reaches the timeline.**

Models are configured only via environment variables (`OPENAI_PLANNER_MODEL`, `ANTHROPIC_VISION_MODEL`, …).
Prompts live in `cutpilot/ai/prompts/*.md` (one per task) and are rendered with `{{var}}` substitution.

## Media understanding

| Step | Implementation | Cache key |
|---|---|---|
| Transcription | OpenAI `whisper-1` (verbose JSON, word timestamps, auto-chunked), or local `faster-whisper` / WhisperX | transcript by `content_hash` + provider, reused across the owner's projects |
| Diarization | pyannote 3.1 when `LOCAL_DIARIZATION_ENABLED` + `HF_TOKEN`; else single speaker | — |
| Silence | ffmpeg `silencedetect` (threshold/min duration from project settings) + EBU R128 loudness | `(content_hash, params)` |
| Filler words | word-level match of a configurable phrase list (multi-word) | `(transcript, list)` |
| Scenes | PySceneDetect `ContentDetector` on the proxy + per-scene thumbnails | `(content_hash, params)` |
| Content | hierarchical: transcript → ~700-word sections → `SectionAnalysis` → `ProjectSummary` (chapters normalised to media duration) | `(transcript hash, context)` |
| Vision | 1–3 representative frames per scene (+ periodic in long scenes), batches of 8 low-detail images → `VisionBatch` | `(content_hash, params)` |

## Planner

`cutpilot/ai/planner.py` — `EditingPlannerProvider` (+ `OpenAIEditingPlanner`, `AnthropicEditingPlanner`,
auto). Input context (`ai/context.py`) is token-budgeted: timeline summary, analysis digest, and the
transcript verbatim up to ~6000 words, otherwise section summaries plus keyword-retrieved segments.
Output: `EditDecisionList` (`timeline/operations.py`). After validation the planner:
1. tags every op `source: ai`, defaults `asset_id` to the primary asset;
2. **expands macros** (`ai/expansion.py`): `silence_removal auto` / `filler_word_removal auto` from stored
   analysis, `caption auto` into word-timed cues from the transcript;
3. **dry-runs** the operations on the current document — anything the engine rejects is reported, never applied.

## Chat editor

`cutpilot/ai/chat.py` runs a bounded tool loop (≤ 8 rounds) with the tools in `ai/tools.py`
(`get_transcript`, `get_timeline`, `get_audio_analysis`, `get_scene_metadata`, `get_content_analysis`,
`plan_edit`, `remove_segment`, `remove_silences`, `remove_filler_words`, `create_cut`, `add_caption`,
`add_zoom`, `add_broll`, `reframe_clip`, `adjust_audio`, `create_short`, `render_video`). Tools read data
or **stage** operations; side effects (Shorts, render) only start when the user applies. The turn runs as
an `EDIT_PLANNING` job and the assistant message carries a `proposal` (`pending → proposed → applied|rejected`).

## Creator features

- Highlights: `ai/highlight_analyzer.py` — factors are explicit (informative, surprising, funny, emotional,
  hook strength, clarity, self-contained); the composite is a documented weighted sum.
- Shorts: `workers/tasks/ai.py::generate_shorts_task` — hook-first ordering (phrase located in the
  transcript), jump cuts from analysis, zooms at key statements, captions, 9:16 with subject tracking.
- B-roll: `services/broll_service.py` — `BrollProvider` interface; library matching by filename + vision
  descriptions. Stock providers plug in here.

## Cost control

- Vision only on sampled frames (`max_frames` default 48), low-detail images.
- Long transcripts reduced by retrieval before planning.
- All analysis cached by content hash; transcripts reused across projects.
- `GET /api/projects/{id}/ai-usage` and `GET /api/me/ai-usage` aggregate `ai_requests`.
