"""Approximate list prices (USD per 1M tokens) for cost estimation. Adjust as needed."""

from __future__ import annotations

PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-5": (1.25, 10.00),
    "o3": (2.00, 8.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
}

TRANSCRIPTION_PER_MINUTE: dict[str, float] = {
    "whisper-1": 0.006,
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    best = None
    for prefix, rates in PRICING.items():
        if model.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, rates)
    if best is None:
        return 0.0
    inp, out = best[1]
    return round(input_tokens / 1e6 * inp + output_tokens / 1e6 * out, 6)


def estimate_transcription_cost(model: str, minutes: float) -> float:
    return round(TRANSCRIPTION_PER_MINUTE.get(model, 0.0) * minutes, 6)
