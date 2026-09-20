# Architecture

CutPilot AI is a project-based, non-destructive, AI-assisted video editor. The core principle:
**the LLM plans; deterministic tools execute.** No model ever touches media bytes.

```
User request ──► Media understanding ──► AI editing planner ──► Structured EDL (JSON)
      ──► Timeline document (versioned, immutable snapshots) ──► FFmpeg render engine ──► MP4
```

## Services

| Service | Role | Tech |
|---|---|---|
| `web` | Editor UI. Proxies `/api/*` to the API so httpOnly auth cookies stay same-origin | Next.js 15, React 18, Tailwind v4, Zustand, TanStack Query |
| `api` | REST + SSE. Auth, projects, uploads, timeline versioning, chat/proposals, render/export orchestration | FastAPI, SQLAlchemy 2 (async), Alembic |
| `worker-media` | Queues `media`, `render`: ffprobe, proxies, thumbnails, audio extraction, waveform peaks, rendering, exports | Celery, FFmpeg, Pillow |
| `worker-ai` | Queue `ai`: transcription, silence/filler/scene detection, LLM analysis, vision, planner, chat, highlights, Shorts, thumbnails, face tracking | Celery, OpenAI/Anthropic SDKs, PySceneDetect, OpenCV |
| `postgres` | System of record | PostgreSQL 16 |
| `redis` | Celery broker/result + pub/sub for real-time events + rate limiting | Redis 7 |
| `minio` (optional) | S3-compatible object storage for production-like setups (`--profile s3`) | MinIO |

The API and workers share one Python package (`apps/api/cutpilot`), so models, the timeline engine
and the render compiler are the same code everywhere.

## Backend package layout

```
cutpilot/
  core/        settings (pydantic-settings), constants (product name), errors, logging, security (argon2 + JWT)
  db/          SQLAlchemy models, async + sync session factories
  api/         routes (auth, projects, assets, timeline, analysis, chat, render, creator, system), deps, middleware
  services/    business logic: auth, projects, assets/uploads, jobs/events, timeline versioning, analysis, chat,
               pipeline orchestration, render/export, creator (highlights/shorts/broll/multicam/sequence)
  timeline/    document model, operation schema (EDL), deterministic engine, helpers
  media/       ffmpeg/ffprobe wrappers, upload validation, proxy/thumbnail/audio/waveform, silence, scenes,
               face tracking (YuNet), thumbnail scoring
  analysis/    filler detection, waveform cross-correlation (multicam)
  ai/          provider abstraction (openai/anthropic), router with fallback + JSON repair loop, prompts/,
               transcription providers, diarization, transcript analyzer, vision, planner, tools, chat,
               macro expansion, highlight analyzer, usage/pricing
  render/      timeline → FFmpeg compiler, captions (SRT/VTT/ASS + PNG raster), presets, exporters, reframe keys
  workers/     Celery app, job lifecycle wrapper, tasks (media, analysis, ai, render)
```

## Data flow: upload → edit → export

1. **Upload** — chunked PUTs to a `UploadSession`; on complete a pending `MediaAsset` + `UPLOAD_PROCESSING`
   job. The worker assembles, validates magic bytes, hashes (dedupe), stores the immutable original,
   then derives proxy (720p H.264), thumbnail, 16 kHz WAV and waveform peaks. Originals are appended to the
   primary timeline as a new **system** version.
2. **Analysis** — `POST /analyze` fans out Celery chains: transcription → content analysis → highlights;
   scenes → vision → thumbnails; audio analysis. Every result is an `AnalysisResult` cached by
   `(content_hash, params_hash)`. Transcripts are reused across a user's projects by content hash.
3. **AI editing** — chat (`EDIT_PLANNING` job) runs the tool loop; tools *stage* validated operations; the
   planner produces an `EditDecisionList` (JSON schema validated, repaired, dry-run against the timeline).
   The user previews (non-committing), applies (new **ai** version, operations recorded) or rejects.
4. **Manual editing** — the timeline UI writes new **user** versions (`PUT /timeline` for drag/trim, or
   operations for split/delete/etc.). Undo/redo move the current-version pointer; restore creates a new version.
5. **Render** — `RENDERING` job compiles the current version to a filter graph and encodes with FFmpeg,
   emitting progress via SSE. Exports produce MP4 (via render), SRT/VTT/ASS, OTIO, EDL, FCPXML.

## Real-time events

Workers publish JSON events to Redis channels `events:project:{id}` / `events:user:{id}`; the API relays
them as Server-Sent Events (`GET /api/events/projects/{id}`) with heartbeats. The web app keeps its
TanStack Query caches fresh from these events (`lib/events.ts`).

## Storage layout

```
projects/{project_id}/
  originals/ proxies/ audio/ thumbnails/ frames/ captions/ renders/ exports/ analysis/ uploads/
```
`Storage` (`cutpilot/storage`) abstracts local disk and S3-compatible backends (signed URLs for direct
streaming/download when available; the API streams with HTTP range support otherwise).

## Security

httpOnly SameSite=Lax cookies + a required `X-Requested-With` header on mutating requests (CSRF),
argon2 password hashing, short-lived access tokens with refresh rotation, per-route ownership checks
(`OwnedProject` dependency), upload extension/MIME/magic-byte validation and size limits, request body
limits, Redis sliding-window rate limits (global + AI), security headers, no secrets in the browser,
parameterised SQL via SQLAlchemy.

## Database

See `apps/api/cutpilot/db/models/`. Key tables: `users`, `projects`, `media_assets`, `media_metadata`,
`upload_sessions`, `transcripts`, `transcript_segments`, `transcript_words`, `speakers`, `scenes`,
`analysis_results`, `timelines`, `timeline_versions` (JSONB document = source of truth), `edit_operations`,
`jobs`, `renders`, `exports`, `ai_requests`, `chat_sessions`, `chat_messages`, `captions`, `highlights`,
`password_reset_tokens`. UUID keys, timezone-aware timestamps, Alembic migrations.

Design note: timeline tracks/clips live inside the version's JSON document rather than in normalised
`timeline_tracks` / `timeline_clips` tables. Every edit snapshots the whole document, which makes
undo/redo/restore/compare trivial and keeps the render input self-contained. `edit_operations` records
the structured operations that produced each version.
