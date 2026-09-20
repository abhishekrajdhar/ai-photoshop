from __future__ import annotations

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import func, select, text

from cutpilot.api.deps import CurrentUser, DBSession, OwnedProject, rate_limit
from cutpilot.core.config import get_settings
from cutpilot.core.constants import API_VERSION, PRODUCT_NAME
from cutpilot.db.models import AIRequest, Project

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "product": PRODUCT_NAME, "version": API_VERSION}


@router.get("/ready")
async def ready(db: DBSession) -> dict[str, object]:
    """Readiness: database and Redis reachable. Returns 503-style payload with per-dependency status."""
    checks: dict[str, str] = {}
    try:
        await db.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"
    settings = get_settings()
    try:
        client = Redis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc.__class__.__name__}"
    from cutpilot.ai.router import available_providers

    checks["ai_providers"] = ",".join(available_providers()) or "none"
    ok = all(v == "ok" for k, v in checks.items() if k in ("database", "redis"))
    return {"status": "ready" if ok else "degraded", "checks": checks}


@router.get("/projects/{project_id}/ai-usage", dependencies=[Depends(rate_limit)])
async def project_ai_usage(project: OwnedProject, db: DBSession) -> dict[str, object]:
    rows = (
        await db.execute(
            select(
                AIRequest.provider,
                AIRequest.model,
                AIRequest.operation,
                func.count(),
                func.sum(AIRequest.input_tokens),
                func.sum(AIRequest.output_tokens),
                func.sum(AIRequest.estimated_cost_usd),
                func.sum(AIRequest.latency_ms),
            )
            .where(AIRequest.project_id == project.id)
            .group_by(AIRequest.provider, AIRequest.model, AIRequest.operation)
        )
    ).all()
    items = [
        {
            "provider": p,
            "model": m,
            "operation": op,
            "requests": int(n),
            "input_tokens": int(i or 0),
            "output_tokens": int(o or 0),
            "estimated_cost_usd": round(float(c or 0), 4),
            "avg_latency_ms": int((lat or 0) / max(1, n)),
        }
        for p, m, op, n, i, o, c, lat in rows
    ]
    return {
        "project_id": str(project.id),
        "total_cost_usd": round(sum(x["estimated_cost_usd"] for x in items), 4),
        "total_requests": sum(x["requests"] for x in items),
        "items": items,
    }


@router.get("/me/ai-usage", dependencies=[Depends(rate_limit)])
async def my_ai_usage(user: CurrentUser, db: DBSession) -> dict[str, object]:
    rows = (
        await db.execute(
            select(
                Project.id,
                Project.name,
                func.count(AIRequest.id),
                func.sum(AIRequest.estimated_cost_usd),
            )
            .join(AIRequest, AIRequest.project_id == Project.id)
            .where(Project.owner_id == user.id)
            .group_by(Project.id, Project.name)
        )
    ).all()
    items = [
        {
            "project_id": str(pid),
            "name": name,
            "requests": int(n),
            "estimated_cost_usd": round(float(c or 0), 4),
        }
        for pid, name, n, c in rows
    ]
    return {
        "total_cost_usd": round(sum(x["estimated_cost_usd"] for x in items), 4),
        "projects": items,
    }
