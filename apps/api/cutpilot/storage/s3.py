"""S3-compatible storage (AWS S3, Cloudflare R2, MinIO)."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from cutpilot.core.config import get_settings
from cutpilot.storage.base import Storage


class S3Storage(Storage):
    def __init__(self) -> None:
        s = get_settings()
        self.bucket = s.s3_bucket
        self.ttl = s.s3_signed_url_ttl_seconds
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path" if s.s3_force_path_style else "auto"}),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except ClientError:
                pass  # Bucket managed externally (e.g. R2); uploads will surface errors.

    def put_file(self, key: str, local_path: str | Path, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.upload_file(str(local_path), self.bucket, key, ExtraArgs=extra or None)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        kwargs = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **kwargs)

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()  # type: ignore[no-any-return]

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def size(self, key: str) -> int:
        return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix: str) -> None:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})

    def local_path(self, key: str) -> Path | None:
        return None

    @contextmanager
    def as_local_file(self, key: str, suffix: str = "") -> Iterator[Path]:
        work = Path(get_settings().work_dir)
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=work, suffix=suffix or Path(key).suffix, delete=False) as tmp:
            path = Path(tmp.name)
        try:
            self.client.download_file(self.bucket, key, str(path))
            yield path
        finally:
            path.unlink(missing_ok=True)

    def signed_url(self, key: str, *, expires_in: int | None = None, filename: str | None = None) -> str | None:
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in or self.ttl)  # type: ignore[no-any-return]

    def open_stream(self, key: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        rng = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
        body = self.client.get_object(Bucket=self.bucket, Key=key, Range=rng)["Body"]
        yield from body.iter_chunks(1024 * 1024)
