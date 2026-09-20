"""Provider router: preferred provider with automatic fallback + JSON validation/repair loop."""

from __future__ import annotations

import json
import uuid
from functools import lru_cache
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from cutpilot.ai.providers.anthropic_provider import AnthropicProvider
from cutpilot.ai.providers.base import LLMProvider, LLMResponse, Message, ToolSpec
from cutpilot.ai.providers.openai_provider import OpenAIProvider
from cutpilot.ai.usage import log_usage
from cutpilot.core.config import AIProviderName, get_settings
from cutpilot.core.errors import AIConfigurationError, AIProviderError
from cutpilot.core.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


@lru_cache
def _provider(name: AIProviderName) -> LLMProvider | None:
    settings = get_settings()
    if not settings.provider_key(name):
        return None
    try:
        return OpenAIProvider() if name == "openai" else AnthropicProvider()
    except AIProviderError:
        return None


def available_providers() -> list[AIProviderName]:
    settings = get_settings()
    order: list[AIProviderName] = [settings.ai_provider]
    if settings.ai_fallback_provider and settings.ai_fallback_provider not in order:
        order.append(settings.ai_fallback_provider)
    for name in ("openai", "anthropic"):
        if name not in order:
            order.append(name)  # type: ignore[arg-type]
    return [n for n in order if _provider(n) is not None]


def provider_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "preferred": settings.ai_provider,
        "fallback": settings.ai_fallback_provider,
        "available": available_providers(),
        "configured": bool(available_providers()),
        "models": {
            "openai": {
                "planner": settings.openai_planner_model,
                "vision": settings.openai_vision_model,
            },
            "anthropic": {
                "planner": settings.anthropic_planner_model,
                "vision": settings.anthropic_vision_model,
            },
        },
    }


def reset_provider_cache() -> None:
    _provider.cache_clear()


class AIRouter:
    """Runs completions against the preferred provider, falling back on provider errors."""

    def __init__(
        self,
        session: Session | None = None,
        *,
        project_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ):
        self.session = session
        self.project_id = project_id
        self.user_id = user_id

    def complete(
        self,
        *,
        operation: str,
        messages: list[Message],
        system: str | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        schema_model: type[BaseModel] | None = None,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        purpose: Literal["planner", "vision"] = "planner",
        meta: dict[str, Any] | None = None,
    ) -> LLMResponse:
        providers = available_providers()
        if not providers:
            raise AIConfigurationError(
                "No AI provider configured. Set OPENAI_API_KEY and/or ANTHROPIC_API_KEY."
            )
        last_error: Exception | None = None
        for name in providers:
            provider = _provider(name)
            assert provider is not None
            model = provider.default_model(purpose)
            try:
                res = provider.complete(
                    messages=messages,
                    system=system,
                    json_schema=json_schema,
                    schema_name=schema_name,
                    schema_model=schema_model,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model=model,
                )
                log_usage(
                    self.session,
                    provider=name,
                    model=model,
                    operation=operation,
                    project_id=self.project_id,
                    user_id=self.user_id,
                    response=res,
                    meta=meta,
                )
                return res
            except AIProviderError as exc:
                last_error = exc
                log_usage(
                    self.session,
                    provider=name,
                    model=model,
                    operation=operation,
                    project_id=self.project_id,
                    user_id=self.user_id,
                    success=False,
                    error=str(exc),
                    meta=meta,
                )
                log.warning(
                    "ai_provider_failed", provider=name, operation=operation, error=str(exc)
                )
                continue
        raise AIProviderError(f"All AI providers failed: {last_error}")

    def complete_structured(
        self,
        schema: type[T],
        *,
        operation: str,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        purpose: Literal["planner", "vision"] = "planner",
        repair_attempts: int = 2,
        meta: dict[str, Any] | None = None,
    ) -> tuple[T, LLMResponse]:
        """Structured completion with validation → retry → repair. Never returns unvalidated data."""
        json_schema = schema.model_json_schema()
        schema_name = schema.__name__
        convo = list(messages)
        last_res: LLMResponse | None = None
        last_err = "no response"
        for attempt in range(repair_attempts + 1):
            res = self.complete(
                operation=operation,
                messages=convo,
                system=system,
                json_schema=json_schema,
                schema_name=schema_name,
                schema_model=schema,
                max_tokens=max_tokens,
                temperature=temperature,
                purpose=purpose,
                meta={**(meta or {}), "attempt": attempt},
            )
            last_res = res
            if res.json is not None:
                try:
                    return schema.model_validate(res.json), res
                except ValidationError as exc:
                    last_err = _summarize_validation_error(exc)
            else:
                last_err = "response was not a JSON object"
            log.warning(
                "ai_structured_invalid", operation=operation, attempt=attempt, error=last_err[:300]
            )
            # Repair: feed the invalid output + errors back and ask for a corrected object.
            convo = [
                *messages,
                Message(
                    role="assistant", content=(res.raw_text or json.dumps(res.json or {}))[:12000]
                ),
                Message(
                    role="user",
                    content=f"Your previous JSON did not validate against the schema. Errors:\n{last_err}\n\nReturn a corrected JSON object only, matching the schema exactly.",
                ),
            ]
        raise AIProviderError(
            f"AI returned invalid structured output after {repair_attempts + 1} attempts: {last_err[:400]}",
            details={"last_response": (last_res.raw_text or "")[:2000] if last_res else ""},
        )


def _summarize_validation_error(exc: ValidationError) -> str:
    lines = []
    for e in exc.errors()[:12]:
        loc = ".".join(str(x) for x in e.get("loc", []))
        lines.append(f"- {loc}: {e.get('msg')}")
    return "\n".join(lines)
