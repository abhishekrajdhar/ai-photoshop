from __future__ import annotations

import time
from typing import Any, Literal

from anthropic import Anthropic

from cutpilot.ai.providers.base import LLMProvider, LLMResponse, Message, ToolCall, ToolSpec
from cutpilot.ai.providers.openai_provider import _loads_lenient
from cutpilot.core.config import get_settings
from cutpilot.core.errors import AIProviderError


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None):
        s = get_settings()
        key = api_key or s.anthropic_api_key
        if not key:
            raise AIProviderError("ANTHROPIC_API_KEY is not configured")
        self.client = Anthropic(
            api_key=key, timeout=s.ai_request_timeout_seconds, max_retries=s.ai_max_retries
        )

    def default_model(self, purpose: Literal["planner", "vision"]) -> str:
        return (
            get_settings().planner_model("anthropic")
            if purpose == "planner"
            else get_settings().vision_model("anthropic")
        )

    @staticmethod
    def _content(msg: Message) -> str | list[dict[str, Any]]:
        if not msg.images and not msg.tool_calls and msg.tool_call_id is None:
            return msg.content
        parts: list[dict[str, Any]] = []
        if msg.role == "tool":
            return [
                {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content,
                }
            ]
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
            # Anthropic requires alternating roles; merge consecutive same-role messages.
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
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        model = model or self.default_model("planner")
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": self._messages(messages),
        }
        if system:
            kwargs["system"] = system
        tool_defs: list[dict[str, Any]] = []
        if json_schema is not None:
            # Structured output via a forced tool call: the model must "emit" the schema.
            tool_defs.append(
                {
                    "name": schema_name,
                    "description": "Return the structured result.",
                    "input_schema": _loosen(json_schema),
                }
            )
            kwargs["tool_choice"] = {"type": "tool", "name": schema_name}
        if tools:
            tool_defs.extend(
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            )
        if tool_defs:
            kwargs["tools"] = tool_defs
        started = time.perf_counter()
        try:
            res = self.client.messages.create(**kwargs)
        except Exception as exc:
            raise AIProviderError(f"Anthropic request failed: {exc}") from exc
        latency = int((time.perf_counter() - started) * 1000)
        text_parts: list[str] = []
        parsed: dict[str, Any] | None = None
        tool_calls: list[ToolCall] = []
        for block in res.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                if json_schema is not None and block.name == schema_name:
                    parsed = dict(block.input) if isinstance(block.input, dict) else None
                else:
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
        )


def _loosen(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic schemas use $defs/$ref which tool input_schema handles, but drop unsupported keys."""
    cleaned = dict(schema)
    cleaned.pop("title", None)
    return cleaned
