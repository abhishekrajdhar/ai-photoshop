"""Local filesystem storage (development default)."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cutpilot.storage.base import Storage


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("storage key escapes root")
        return path

    def put_file(self, key: str, local_path: str | Path, content_type: str | None = None) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = Path(local_path)
        try:
            # Same filesystem: atomic rename is cheapest; otherwise copy.
            if src.stat().st_dev == dest.parent.stat().st_dev:
                os.replace(src, dest)
                return
        except OSError:
            pass
        shutil.copyfile(src, dest)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    def local_path(self, key: str) -> Path | None:
        path = self._path(key)
        return path if path.is_file() else None

    @contextmanager
    def as_local_file(self, key: str, suffix: str = "") -> Iterator[Path]:
        yield self._path(key)

    def signed_url(self, key: str, *, expires_in: int | None = None, filename: str | None = None) -> str | None:
        return None

    def open_stream(self, key: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        path = self._path(key)
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = None if end is None else end - start + 1
            while True:
                chunk = fh.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
                if not chunk:
                    break
                yield chunk
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
