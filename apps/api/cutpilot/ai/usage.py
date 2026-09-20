"""AI usage logging (never logs keys or raw prompts)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from cutpilot.ai.pricing import estimate_cost
from cutpilot.ai.providers.base import LLMResponse
from cutpilot.core.logging import get_logger
from cutpilot.db.models import AIRequest

log = get_logger(__name__)


def log_usage(
    session: Session | None,
    *,
    provider: str,
    model: str,
    operation: str,
    project_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    response: LLMResponse | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    error: str | None = None,
    cost_usd: float | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    if response is not None:
        input_tokens, output_tokens, latency_ms = (
            response.input_tokens,
            response.output_tokens,
            response.latency_ms,
        )
    cost = cost_usd if cost_usd is not None else estimate_cost(model, input_tokens, output_tokens)
    log.info(
        "ai_request",
        provider=provider,
        model=model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_usd=cost,
        success=success,
    )
    if session is None:
        return
    try:
        session.add(
            AIRequest(
                project_id=project_id,
                user_id=user_id,
                provider=provider,
                model=model,
                operation=operation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=cost,
                success=success,
                error=(error or None) and error[:2000],
                meta=meta or {},
            )
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        log.warning("ai_usage_log_failed", error=str(exc))
