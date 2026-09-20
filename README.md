# CutPilot AI

AI-assisted, non-destructive video editing platform. Upload raw footage, describe the edit in
natural language, review the proposed operations on a professional multi-track timeline, adjust
anything by hand, and export a finished MP4.

> The product name lives in one place per app: `apps/api/cutpilot/core/constants.py`
> (`PRODUCT_NAME`) and `NEXT_PUBLIC_APP_NAME` for the web app.

## Architecture at a glance

```
User request → Media understanding → AI editing planner → Structured EDL (JSON)
             → Timeline document (versioned) → FFmpeg render engine → Final video
```

- **The LLM never touches media.** It produces validated JSON edit operations; FFmpeg, PySceneDetect,
  OpenCV and OpenTimelineIO do the deterministic work.
- **Originals are immutable.** Every edit is a timeline operation; every AI/user edit creates a new
  timeline version with undo / redo / restore / compare.
- **Async everywhere.** Heavy work runs in Celery workers (`media`, `ai`, `render` queues) with
  real-time progress via Server-Sent Events.

| Layer    | Stack |
|----------|-------|
| Web      | Next.js 15 (App Router), TypeScript strict, Tailwind v4, shadcn-style UI, Zustand, TanStack Query |
| API      | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, PostgreSQL |
| Workers  | Celery + Redis |
| Media    | FFmpeg / FFprobe, PySceneDetect, OpenCV, OpenTimelineIO |
| AI       | OpenAI + Anthropic (provider router with fallback), optional WhisperX / faster-whisper / pyannote |
| Storage  | Local filesystem (dev) or any S3-compatible store (AWS S3, Cloudflare R2, MinIO) |

## Quick start

```bash
cp .env.example .env          # add OPENAI_API_KEY and/or ANTHROPIC_API_KEY
docker compose up --build
```

- Web app: http://localhost:3000
- API docs (OpenAPI): http://localhost:8000/api/docs

## Repository layout

```
apps/
  api/            FastAPI app + Celery workers (Python package `cutpilot`)
    cutpilot/
      ai/         provider router, planner, vision, prompts/, tool-calling
      api/        routes, deps, middleware
      db/         SQLAlchemy models, sessions
      media/      ffmpeg/ffprobe wrappers, proxies, audio, scenes, silence, frames
      render/     timeline → FFmpeg compiler, captions (ASS), presets
      services/   business logic
      timeline/   timeline document model, operation schema, deterministic engine, OTIO/EDL export
      workers/    Celery app + tasks
    alembic/      migrations
    tests/
  web/            Next.js app
infrastructure/docker/   Dockerfiles
docs/             ARCHITECTURE, AI_PIPELINE, TIMELINE, RENDERING, DEPLOYMENT, API
```

## Development

```bash
# Backend (local venv)
cd apps/api && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/ruff check cutpilot tests

# Frontend
cd apps/web && npm install && npm run dev
npm run typecheck && npm run lint && npm test
```

### Running the stack natively (without Docker)

```bash
# 1. Postgres + Redis running locally, then in apps/api:
cp ../../.env.example .env   # set DATABASE_URL / REDIS_URL / LOCAL_STORAGE_ROOT / WORK_DIR to local paths
.venv/bin/alembic upgrade head
.venv/bin/uvicorn cutpilot.main:app --port 8000 --reload
# Optional: local transcription without cloud keys (CPU): uv pip install --python .venv/bin/python -e ".[local-transcription]"
#           then set LOCAL_TRANSCRIPTION_ENABLED=true TRANSCRIPTION_PROVIDER=faster_whisper
# 2. Worker — on macOS use the threads pool (Celery's default prefork/spawn pool crashes on macOS + Python 3.12):
.venv/bin/celery -A cutpilot.workers.celery_app:celery_app worker -Q media,ai,render -P threads --concurrency=4
# 3. Web:
cd ../web && INTERNAL_API_URL=http://localhost:8000 npm run dev
```

See `docs/` for architecture, AI pipeline, timeline, rendering and deployment details.
