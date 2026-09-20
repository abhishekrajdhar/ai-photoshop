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
