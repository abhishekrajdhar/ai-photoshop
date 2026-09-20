from __future__ import annotations

import json
import time
from typing import Any, Literal

from openai import OpenAI

from cutpilot.ai.providers.base import LLMProvider, LLMResponse, Message, ToolCall, ToolSpec
from cutpilot.core.config import get_settings
from cutpilot.core.errors import AIProviderError


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None = None):
        s = get_settings()
        key = api_key or s.openai_api_key
        if not key:
            raise AIProviderError("OPENAI_API_KEY is not configured")
        self.client = OpenAI(
            api_key=key, timeout=s.ai_request_timeout_seconds, max_retries=s.ai_max_retries
        )

    def default_model(self, purpose: Literal["planner", "vision"]) -> str:
        return (
            get_settings().planner_model("openai")
            if purpose == "planner"
            else get_settings().vision_model("openai")
        )

    @staticmethod
    def _content(msg: Message) -> str | list[dict[str, Any]]:
        if not msg.images:
            return msg.content
        parts: list[dict[str, Any]] = []
        if msg.content:
            parts.append({"type": "text", "text": msg.content})
        for img in msg.images:
            if img.label:
                parts.append({"type": "text", "text": img.label})
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img.media_type};base64,{img.b64()}",
                        "detail": "low",
                    },
                }
            )
        return parts

    def _messages(self, messages: list[Message], system: str | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "tool":
                out.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content}
                )
            elif m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            else:
                out.append({"role": m.role, "content": self._content(m)})
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
            "messages": self._messages(messages, system),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_schema is not None:
            # json_object mode + schema in the prompt keeps compatibility across models;
            # the caller validates with Pydantic and repairs/rejects.
            kwargs["response_format"] = {"type": "json_object"}
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            kwargs["tool_choice"] = "auto"
        started = time.perf_counter()
        try:
            res = self.client.chat.completions.create(**kwargs)
        except Exception as exc:  # SDK-specific errors are wrapped so the router can fall back
            raise AIProviderError(f"OpenAI request failed: {exc}") from exc
        latency = int((time.perf_counter() - started) * 1000)
        choice = res.choices[0]
        text = choice.message.content or None
        tool_calls: list[ToolCall] = []
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        parsed: dict[str, Any] | None = None
        if json_schema is not None and text:
            parsed = _loads_lenient(text)
        usage = res.usage
        return LLMResponse(
            provider=self.name,
            model=model,
            text=text,
            json=parsed,
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency,
            stop_reason=choice.finish_reason,
            raw_text=text,
        )


def _loads_lenient(text: str) -> dict[str, Any] | None:
    """Parse JSON, tolerating code fences and leading prose."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {"items": obj}
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(t[start : end + 1])
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
    return None
