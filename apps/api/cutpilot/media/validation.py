"""Upload validation: extension, MIME and magic-byte sniffing, size limits."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from cutpilot.core.config import get_settings
from cutpilot.core.constants import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from cutpilot.core.errors import ValidationFailed

_SIGNATURES: list[tuple[bytes, int, str]] = [
    # (magic, offset, media family)
    (b"ftyp", 4, "video"),  # MP4 / MOV / M4A (checked again below)
    (b"\x1a\x45\xdf\xa3", 0, "video"),  # Matroska / WebM
    (b"RIFF", 0, "audio"),  # WAV (RIFF....WAVE)
    (b"ID3", 0, "audio"),  # MP3 with ID3
    (b"\xff\xfb", 0, "audio"),  # MP3 frame sync
    (b"\xff\xf3", 0, "audio"),
    (b"\xff\xf2", 0, "audio"),
    (b"\xff\xd8\xff", 0, "image"),  # JPEG
    (b"\x89PNG\r\n\x1a\n", 0, "image"),  # PNG
    (b"RIFF", 0, "image"),  # WebP (RIFF....WEBP)
]


def media_type_for_extension(ext: str) -> str:
    ext = ext.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    raise ValidationFailed(f"Unsupported file type {ext}")


def sniff_media_family(head: bytes) -> str | None:
    if len(head) >= 12 and head[:4] == b"RIFF":
        if head[8:12] == b"WAVE":
            return "audio"
        if head[8:12] == b"WEBP":
            return "image"
        return None
    for magic, offset, family in _SIGNATURES:
        if head[offset : offset + len(magic)] == magic:
            if magic == b"ftyp":
                brand = head[8:12]
                return "audio" if brand in (b"M4A ", b"M4B ") else "video"
            return family
    return None


def validate_upload_request(filename: str, mime_type: str, size_bytes: int) -> tuple[str, str]:
    """Validate declared attributes before any bytes are stored. Returns (extension, media_type)."""
    settings = get_settings()
    ext = Path(filename).suffix.lower()
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise ValidationFailed(
            f"Unsupported file extension '{ext or 'none'}'",
            details={"allowed": sorted(ALLOWED_EXTENSIONS)},
        )
    if size_bytes <= 0:
        raise ValidationFailed("File is empty")
    if size_bytes > settings.max_upload_size:
        raise ValidationFailed(
            f"File exceeds the maximum upload size of {settings.max_upload_size} bytes"
        )
    declared = (mime_type or "").split(";")[0].strip().lower() or (
        mimetypes.guess_type(filename)[0] or "application/octet-stream"
    )
    if declared not in ALLOWED_MIME_TYPES:
        raise ValidationFailed(f"Unsupported MIME type {declared}")
    return ext, media_type_for_extension(ext)


def validate_file_contents(path: str | Path, expected_media_type: str) -> None:
    """Magic-byte check after assembly. MKV/MOV/M4A all resolve to their family."""
    with Path(path).open("rb") as fh:
        head = fh.read(64)
    family = sniff_media_family(head)
    if family is None:
        raise ValidationFailed("File contents do not look like a supported media file")
    # M4A can be declared audio but sniffed as video container; MP4 audio-only is allowed too.
    if family != expected_media_type and not (expected_media_type == "audio" and family == "video"):
        raise ValidationFailed(
            f"File contents ({family}) do not match its extension ({expected_media_type})"
        )


def safe_filename(filename: str) -> str:
    name = os.path.basename(filename).strip().replace("\x00", "")
    return name[:200] or "upload"
