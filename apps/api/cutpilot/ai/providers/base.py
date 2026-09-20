"""Provider-agnostic LLM interface.

Every provider must support:
- plain text completion
- strict JSON output validated against a JSON schema (structured planning)
- image inputs (vision)
- tool calling (the chat editor's internal tools)
"""

from __future__ import annotations

import abc
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ImagePart:
    data: bytes
    media_type: str = "image/jpeg"
    label: str | None = None  # e.g. "frame @ 12.4s"

    @classmethod
    def from_file(cls, path: str | Path, label: str | None = None) -> ImagePart:
        p = Path(path)
        mt = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        return cls(data=p.read_bytes(), media_type=mt, label=label)

    def b64(self) -> str:
        return base64.b64encode(self.data).decode()


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Role
    content: str = ""
    images: list[ImagePart] = field(default_factory=list)
    # assistant messages may carry tool calls; tool messages answer one
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    # Provider-native content blocks of an assistant turn (replayed verbatim by the same provider).
    raw: list[dict[str, Any]] | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


@dataclass
class LLMResponse:
    provider: str
    model: str
    text: str | None = None
    json: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    stop_reason: str | None = None
    raw_text: str | None = None
    raw_content: list[dict[str, Any]] | None = None


class LLMProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    def complete(
        self,
        *,
        messages: list[Message],
        system: str | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        schema_model: type[Any] | None = None,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        """Run one completion. When json_schema is given the response must be a JSON object.
        `schema_model` (a Pydantic class) lets providers use native structured-output helpers."""

    @abc.abstractmethod
    def default_model(self, purpose: Literal["planner", "vision"]) -> str: ...
