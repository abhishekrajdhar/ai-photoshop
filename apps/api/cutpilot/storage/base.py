"""Object-storage abstraction. Keys are project-scoped: projects/{project_id}/{dir}/{name}."""

from __future__ import annotations

import abc
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from cutpilot.core.config import get_settings
from cutpilot.core.constants import STORAGE_DIRS


def build_key(project_id: uuid.UUID | str, directory: str, filename: str) -> str:
    if directory not in STORAGE_DIRS:
        raise ValueError(f"unknown storage directory {directory}")
    safe = os.path.basename(filename).replace("..", "_")
    return f"projects/{project_id}/{directory}/{safe}"


class Storage(abc.ABC):
    """Minimal interface used by the API and workers."""

    @abc.abstractmethod
    def put_file(self, key: str, local_path: str | Path, content_type: str | None = None) -> None: ...

    @abc.abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    @abc.abstractmethod
    def get_bytes(self, key: str) -> bytes: ...

    @abc.abstractmethod
    def exists(self, key: str) -> bool: ...

    @abc.abstractmethod
    def size(self, key: str) -> int: ...

    @abc.abstractmethod
    def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    def delete_prefix(self, prefix: str) -> None: ...

    @abc.abstractmethod
    def local_path(self, key: str) -> Path | None:
        """Return a filesystem path if the object is directly readable (local storage), else None."""

    @abc.abstractmethod
    @contextmanager
    def as_local_file(self, key: str, suffix: str = "") -> Iterator[Path]:
        """Yield a local path for the object (downloading to WORK_DIR if necessary)."""

    @abc.abstractmethod
    def signed_url(self, key: str, *, expires_in: int | None = None, filename: str | None = None) -> str | None:
        """Return a time-limited direct URL, or None when the API must proxy the bytes."""

    @abc.abstractmethod
    def open_stream(self, key: str, start: int = 0, end: int | None = None) -> Iterator[bytes]: ...


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_provider == "s3":
        from cutpilot.storage.s3 import S3Storage

        return S3Storage()
    from cutpilot.storage.local import LocalStorage

    return LocalStorage(settings.local_storage_root)
