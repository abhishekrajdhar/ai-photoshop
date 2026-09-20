from __future__ import annotations

import time
from typing import Any, Literal

import anthropic
from pydantic import BaseModel

from cutpilot.ai.providers.base import LLMProvider, LLMResponse, Message, ToolCall, ToolSpec
from cutpilot.ai.providers.openai_provider import _loads_lenient
from cutpilot.core.config import get_settings
from cutpilot.core.errors import AIProviderError
from cutpilot.core.logging import get_logger

log = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API (SDK 1.x). Structured output via `messages.parse`, tools via tool_use blocks.

    Current models run adaptive thinking by default; assistant turns are replayed with their original
    content blocks (`Message.raw`) so thinking/tool_use blocks round-trip unchanged in tool loops.
    Sampling parameters (temperature/top_p) are not sent — they are rejected by current models.
    """

    name = "anthropic"

    def __init__(self, api_key: str | None = None):
        s = get_settings()
        key = api_key or s.anthropic_api_key
        if not key:
            raise AIProviderError("ANTHROPIC_API_KEY is not configured")
        self.client = anthropic.Anthropic(
            api_key=key, timeout=float(s.ai_request_timeout_seconds), max_retries=s.ai_max_retries
        )
        self.effort = s.anthropic_effort
        # Schemas the API rejected as too complex for constrained decoding → prompted JSON directly.
        self._unconstrained_schemas: set[str] = set()

    def default_model(self, purpose: Literal["planner", "vision"]) -> str:
        return (
            get_settings().planner_model("anthropic")
            if purpose == "planner"
            else get_settings().vision_model("anthropic")
        )

    @staticmethod
    def _content(msg: Message) -> str | list[dict[str, Any]]:
        if msg.role == "tool":
            return [
                {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content,
                }
            ]
        if msg.role == "assistant" and msg.raw:
            return msg.raw  # verbatim replay (thinking + text + tool_use blocks)
        if not msg.images and not msg.tool_calls:
            return msg.content
        parts: list[dict[str, Any]] = []
        if msg.content:
            parts.append({"type": "text", "text": msg.content})
        for img in msg.images:
            if img.label:
                parts.append({"type": "text", "text": img.label})
            parts.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": img.media_type, "data": img.b64()},
                }
            )
        for tc in msg.tool_calls:
            parts.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
        return parts

    def _messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            role = "user" if m.role in ("user", "tool") else "assistant"
            content = self._content(m)
            # Merge consecutive same-role turns (e.g. several tool results) into one message.
            if out and out[-1]["role"] == role:
                prev = out[-1]["content"]
                prev_list = prev if isinstance(prev, list) else [{"type": "text", "text": prev}]
                cur_list = (
                    content if isinstance(content, list) else [{"type": "text", "text": content}]
                )
                out[-1]["content"] = prev_list + cur_list
            else:
                out.append({"role": role, "content": content})
        return out

    def complete(
        self,
        *,
        messages: list[Message],
        system: str | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        schema_model: type[BaseModel] | None = None,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,  # accepted for interface parity; not sent
        model: str | None = None,
    ) -> LLMResponse:
        model = model or self.default_model("planner")
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max(max_tokens, 1024),
            "messages": self._messages(messages),
        }
        if system:
            kwargs["system"] = system
        output_config: dict[str, Any] = {}
        if self.effort:
            output_config["effort"] = self.effort
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        started = time.perf_counter()
        parsed: dict[str, Any] | None = None
        try:
            res = None
            if json_schema is None or schema_name not in self._unconstrained_schemas:
                try:
                    res, parsed = _structured_call(
                        self.client, dict(kwargs), dict(output_config), json_schema, schema_model
                    )
                except anthropic.BadRequestError as exc:
                    # Constrained decoding has schema-complexity limits; remember the schema and
                    # fall back to prompted JSON, which the router still validates and repairs.
                    if json_schema is None or "schema" not in exc.message.lower():
                        raise
                    self._unconstrained_schemas.add(schema_name)
                    log.warning(
                        "anthropic_schema_fallback",
                        model=model,
                        schema=schema_name,
                        error=exc.message[:160],
                    )
            if res is None:
                plain = dict(kwargs)
                plain["system"] = (plain.get("system") or "") + (
                    "\n\nRespond with a single JSON object that matches the requested schema "
                    "exactly. No prose, no code fences."
                )
                if self.effort:
                    plain["output_config"] = {"effort": self.effort}
                res = self.client.messages.create(**plain)
                parsed = None
        except anthropic.RateLimitError as exc:
            raise AIProviderError(f"Anthropic rate limited: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise AIProviderError(
                f"Anthropic request failed ({exc.status_code}): {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise AIProviderError(f"Anthropic connection error: {exc}") from exc
        except Exception as exc:  # SDK parse/validation errors
            raise AIProviderError(f"Anthropic request failed: {exc}") from exc
        latency = int((time.perf_counter() - started) * 1000)
        if res.stop_reason == "refusal":
            raise AIProviderError("Anthropic declined the request (refusal)")
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in res.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input) if isinstance(block.input, dict) else {},
                    )
                )
        text = "\n".join(text_parts) or None
        if json_schema is not None and parsed is None and text:
            parsed = _loads_lenient(text)
        return LLMResponse(
            provider=self.name,
            model=model,
            text=text,
            json=parsed,
            tool_calls=tool_calls,
            input_tokens=res.usage.input_tokens,
            output_tokens=res.usage.output_tokens,
            latency_ms=latency,
            stop_reason=res.stop_reason,
            raw_text=text,
            raw_content=[b.model_dump(mode="json") for b in res.content],
        )


def _structured_call(
    client: anthropic.Anthropic,
    kwargs: dict[str, Any],
    output_config: dict[str, Any],
    json_schema: dict[str, Any] | None,
    schema_model: type[BaseModel] | None,
) -> tuple[Any, dict[str, Any] | None]:
    if json_schema is not None and schema_model is not None:
        if output_config:
            kwargs["output_config"] = output_config
        res = client.messages.parse(output_format=schema_model, **kwargs)
        po = getattr(res, "parsed_output", None)
        parsed = (
            po.model_dump(mode="json")
            if isinstance(po, BaseModel)
            else (dict(po) if po is not None else None)
        )
        return res, parsed
    if json_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": _inline_refs(json_schema)}
    if output_config:
        kwargs["output_config"] = output_config
    return client.messages.create(**kwargs), None


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Self-contained JSON schema: $ref/$defs inlined, titles dropped."""
    defs = schema.get("$defs", {})

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 40:
            return node
        if isinstance(node, dict):
            if (
                "$ref" in node
                and isinstance(node["$ref"], str)
                and node["$ref"].startswith("#/$defs/")
            ):
                target = defs.get(node["$ref"].split("/")[-1], {})
                return {
                    **resolve(target, depth + 1),
                    **{k: v for k, v in node.items() if k != "$ref"},
                }
            return {
                k: resolve(v, depth + 1) for k, v in node.items() if k not in ("title", "$defs")
            }
        if isinstance(node, list):
            return [resolve(v, depth + 1) for v in node]
        return node

    return resolve(schema)


_loosen = _inline_refs
