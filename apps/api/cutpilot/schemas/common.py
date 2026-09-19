"""Consistent API envelope types."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(APIModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class OkResponse(BaseModel):
    ok: bool = True
