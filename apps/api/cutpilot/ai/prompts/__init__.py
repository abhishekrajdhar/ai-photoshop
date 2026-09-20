"""Prompt templates are version-controlled markdown files rendered with simple {{var}} substitution."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent


@lru_cache
def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt template {name} not found")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **variables: object) -> str:
    text = load_prompt(name)
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text
