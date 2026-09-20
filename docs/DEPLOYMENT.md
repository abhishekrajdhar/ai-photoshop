# Deployment

## Local development

```bash
cp .env.example .env         # add OPENAI_API_KEY / ANTHROPIC_API_KEY
docker compose up --build    # web :3000, api :8000 (docs at /api/docs), postgres :5432, redis :6379
docker compose --profile s3 up   # additionally MinIO (:9000, console :9001) with STORAGE_PROVIDER=s3
```
The API container runs migrations on start (`scripts/start-api.sh`). Source folders are bind-mounted for
hot reload (uvicorn `--reload`, `next dev`).

Native (no Docker) instructions are in the README. On macOS run Celery with `-P threads`.

## Production topology (provider-independent)

| Component | Options | Notes |
|---|---|---|
| Web | Vercel, or the `production` target of `infrastructure/docker/web.Dockerfile` | Set `INTERNAL_API_URL` to the API's private URL (rewrites), `NEXT_PUBLIC_APP_NAME`, `NEXT_OUTPUT=standalone` for the container build |
| API | Cloud Run / AWS ECS / Render / Fly | `infrastructure/docker/api.Dockerfile`, command `/app/scripts/start-api.sh`, `APP_ENV=production`, `COOKIE_SECURE=true`, `UVICORN_WORKERS` |
| Workers | Same image, commands `/app/scripts/start-worker.sh media,render` and `... ai` | Scale queues independently; GPU workers (RunPod/Modal/VM) install `.[local-ai]` and set `LOCAL_TRANSCRIPTION_ENABLED=true`, `WHISPER_DEVICE=cuda` |
| PostgreSQL | Neon, Supabase, RDS, Cloud SQL | `DATABASE_URL=postgresql+psycopg://…` |
| Redis | Upstash, ElastiCache, Memorystore | `REDIS_URL=rediss://…` for TLS |
| Storage | Cloudflare R2, S3, MinIO | `STORAGE_PROVIDER=s3`, `S3_ENDPOINT` (empty for AWS), bucket + keys; signed URLs serve media directly |

The API and workers must share `WORK_DIR` **only within a container** (scratch); shared media goes through
object storage. With `STORAGE_PROVIDER=local` all API/worker replicas must mount the same volume.

`infrastructure/deploy/docker-compose.prod.yml` shows a single-host production layout (built images,
no bind mounts, restart policies, MinIO). `infrastructure/deploy/render.yaml` is a Render blueprint.

## Vercel (frontend) + hosted backend

Vercel can host `apps/web`, not the API/workers (they need long-running processes, FFmpeg, Redis and a
persistent filesystem). Recommended split: **Vercel → web**, **Render/Fly/Railway/Cloud Run/VPS → api +
workers**, **Neon/Supabase → Postgres**, **Upstash → Redis**, **R2/S3 → storage**.

1. Deploy the backend first (e.g. `infrastructure/deploy/render.yaml`, or `docker-compose.prod.yml` on a VPS).
   Give it a domain such as `api.example.com` with HTTPS.
2. Create the Vercel project with **Root Directory = `apps/web`** (framework auto-detected: Next.js).
3. Choose one of two wiring modes:

   **A. Direct (recommended, streams and large uploads go straight to the API)** — put the app on a
   sibling subdomain (`app.example.com`) so cookies are same-site:
   - Vercel env: `NEXT_PUBLIC_API_BASE=https://api.example.com/api`, `NEXT_PUBLIC_APP_NAME=CutPilot AI`
   - API env: `APP_URL=https://app.example.com`, `COOKIE_SECURE=true`, `COOKIE_DOMAIN=.example.com`,
     `CORS_ORIGINS=https://<project>.vercel.app` (add preview URLs as needed)

   **B. Proxied (no custom domain)** — keep `NEXT_PUBLIC_API_BASE=/api` and set
   `INTERNAL_API_URL=https://api.example.com` on Vercel; Next.js rewrites forward `/api/*`. This keeps
   cookies first-party on `*.vercel.app`, but SSE and multi-MB chunk uploads pass through Vercel's proxy —
   set `UPLOAD_CHUNK_SIZE=4194304` (4 MiB) on the API and expect job-progress events to arrive with some
   buffering. Use mode A for production.

   If the app and API must live on unrelated sites, set `COOKIE_SAMESITE=none` (implies Secure) on the API.
4. Redeploy the web project; `GET https://api.example.com/api/ready` should report `ready`, and the
   AI panel's status banner disappears once a provider key is configured on the API.

## All-in-one container (no object storage yet)

`infrastructure/deploy/render-all-in-one.yaml` / `apps/api/scripts/start-all.sh` run Redis, the API and
the workers in **one** container with a persistent disk at `/data`. Use it for a single-instance
deployment on Render, Railway or Fly when you don't have S3/R2 yet; move to `render.yaml` +
`STORAGE_PROVIDER=s3` to scale the API and workers independently.

## Hugging Face Space (free single-container backend)

A free Docker Space (2 vCPU, 16 GB RAM) can host the all-in-one backend:

1. Create a **Docker** Space (public), then push this repository to it:
   `git remote add hf https://huggingface.co/spaces/<user>/<space> && git push hf main`
   (the root `Dockerfile` and README front-matter are already in place; port 7860).
2. Space → Settings → **Secrets**: `DATABASE_URL` (Supabase pooler URI, `postgresql+psycopg://…`), `DB_SCHEMA=cutpilot`,
   `JWT_SECRET` (long random string), `ANTHROPIC_API_KEY`, `AI_PROVIDER=anthropic`, `AI_FALLBACK_PROVIDER=` (empty),
   `APP_URL=https://<your-vercel-app>`, `COOKIE_SECURE=true`, `COOKIE_SAMESITE=none`, `CORS_ORIGINS` (extra origins).
3. Point the web app at it: Vercel env `NEXT_PUBLIC_API_BASE=https://<user>-<space>.hf.space/api` and redeploy.

Limits: the container disk is ephemeral (media is lost on rebuild/restart — add R2/S3 with `STORAGE_PROVIDER=s3`
for durability) and the Space sleeps after ~48 h idle.

## Sharing a database (Supabase / existing PostgreSQL)

Set `DB_SCHEMA=cutpilot` (any name) to keep every CutPilot table — and Alembic's version table — inside its
own PostgreSQL schema. Migrations create the schema automatically; the ORM routes all queries through a
schema translate map, so nothing in `public` is touched. Leave it empty for a dedicated database.

## Environment variables

See `.env.example` — every variable is documented there. Required in production: `DATABASE_URL`,
`REDIS_URL`, `JWT_SECRET` (≥ 32 random chars), `APP_URL`, `COOKIE_SECURE=true`, at least one of
`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`, and storage settings.

## Operations

- Health: `GET /api/health` (liveness), `GET /api/ready` (DB + Redis + configured AI providers).
- Logs: structured JSON in production (`LOG_LEVEL`).
- Jobs: retried with exponential backoff (`max_retries` per type), cancellable via `POST /api/jobs/{id}/cancel`,
  `--max-tasks-per-child=50` guards worker memory.
- Rate limits: `RATE_LIMIT_PER_MINUTE` (per client IP) and `AI_RATE_LIMIT_PER_MINUTE` (per user).
- Cost tracking: `ai_requests` table, `GET /api/projects/{id}/ai-usage`, `GET /api/me/ai-usage`.
- Migrations: `alembic upgrade head` (automatic on API start), `alembic revision --autogenerate -m "…"`.
- Email: password reset issues a token and logs the link; wire an email provider in
  `api/routes/auth.py::request_password_reset` to deliver it (in development the token is returned).

## Scaling notes

- Uploads are chunked (`UPLOAD_CHUNK_SIZE`) so the API never holds a whole file; `MAX_UPLOAD_SIZE` caps files.
- Rendering is CPU-bound: give `worker-media` cores and use `preset=veryfast`/`fast` for drafts; proxies
  keep the editor responsive regardless of source resolution.
- Vision/LLM calls are cached by content hash — re-analysis is free unless parameters change.
