# API

Base path `/api`. OpenAPI: `GET /api/openapi.json`, Swagger UI `GET /api/docs`. All responses are JSON;
errors use `{"error": {"code", "message", "details"}}`. Authentication: httpOnly cookies (browser) or
`Authorization: Bearer <access_token>`; mutating cookie requests must send `X-Requested-With`.

## Auth
`POST /auth/register` · `POST /auth/login` · `POST /auth/refresh` · `POST /auth/logout` · `GET/PATCH /auth/me` ·
`POST /auth/change-password` · `POST /auth/password-reset/request` · `POST /auth/password-reset/confirm`

## Projects
`POST /projects` · `GET /projects?include_archived=` · `GET/PATCH/DELETE /projects/{id}` ·
`POST /projects/{id}/archive` · `POST /projects/{id}/duplicate`

## Media
`GET /projects/{id}/assets` · `POST /projects/{id}/assets` (single request, small files) ·
`POST /projects/{id}/uploads` → `PUT /projects/{id}/uploads/{uid}/chunks/{n}` → `POST …/complete` ·
`GET /assets/{id}` · `PATCH /assets/{id}` (rename, role, kind) · `DELETE /assets/{id}` ·
`GET /assets/{id}/stream|original|download|thumbnail|waveform|derived`

## Analysis
`POST /projects/{id}/transcribe` · `POST /projects/{id}/analyze` `{steps:[transcription|audio|scenes|content|vision|highlights|thumbnails], asset_id?, force?}` ·
`GET /projects/{id}/transcript` · `PATCH …/transcript/segments/{sid}` · `PATCH …/transcript/words/{wid}` ·
`PATCH …/transcript/speakers/{spid}` · `GET /projects/{id}/scenes` · `GET …/scenes/{sid}/thumbnail` ·
`GET /projects/{id}/analysis?kind=` · `GET /projects/{id}/ai-status`

## Timeline
`GET /projects/{id}/timelines` · `POST /projects/{id}/timelines` · `DELETE …/timelines/{tid}` ·
`GET /projects/{id}/timeline?timeline_id=` · `PUT …/timeline` (save document) ·
`POST …/timeline/operations` (apply `EditOperation[]`) · `GET …/timeline/versions` ·
`GET …/timeline/versions/{vid}` · `POST …/timeline/versions/{vid}/restore` ·
`GET …/timeline/versions/{a}/compare/{b}` · `POST …/timeline/undo` · `POST …/timeline/redo` ·
`PATCH /projects/{id}/sequence` (caption style, audio processing, aspect/reframe)

## AI editor
`POST /projects/{id}/chat` `{message, session_id?}` → assistant message with `proposal` (job) ·
`POST /projects/{id}/edit` `{instruction, target_platform?, target_duration_seconds?}` ·
`GET /projects/{id}/chat/sessions` · `POST …/chat/sessions` · `GET …/chat/messages/{mid}` ·
`POST …/chat/messages/{mid}/preview|apply|reject`

## Creator
`GET/POST /projects/{id}/highlights` · `POST /projects/{id}/shorts` · `GET/POST /projects/{id}/thumbnails` ·
`POST /projects/{id}/reframe/track` · `GET /projects/{id}/broll/search?q=` · `POST …/broll/resolve` ·
`POST …/broll/place` · `POST /projects/{id}/multicam/sync`

## Render & export
`GET /render/presets` · `POST /projects/{id}/render` · `GET /projects/{id}/renders[/{rid}]` ·
`POST /projects/{id}/exports` `{format: mp4|srt|vtt|ass|otio|edl|fcpxml}` · `GET /projects/{id}/exports` ·
`GET /exports/{id}`

## Jobs & events
`GET /jobs?project_id=&active_only=` · `GET /jobs/{id}` · `POST /jobs/{id}/cancel` ·
`GET /events/stream` · `GET /events/projects/{id}` (SSE: `job.*`, `upload.*`, `<type>.progress|completed`,
`timeline.updated`, `transcript.updated`, `analysis.updated`, `chat.message`, `render.completed`, `export.completed`)

## System
`GET /health` · `GET /ready` · `GET /projects/{id}/ai-usage` · `GET /me/ai-usage`
