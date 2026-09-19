"""Product-level constants. Keep the product name isolated here so it can be renamed."""

PRODUCT_NAME = "CutPilot AI"
PRODUCT_SLUG = "cutpilot"
API_TITLE = f"{PRODUCT_NAME} API"
API_VERSION = "0.1.0"

# Cookie names are derived from the slug so a rename stays consistent.
ACCESS_COOKIE = f"{PRODUCT_SLUG}_access"
REFRESH_COOKIE = f"{PRODUCT_SLUG}_refresh"
CSRF_HEADER = "x-requested-with"

# Storage layout under projects/{project_id}/
STORAGE_DIRS = (
    "originals",
    "proxies",
    "audio",
    "thumbnails",
    "frames",
    "captions",
    "renders",
    "exports",
    "analysis",
    "uploads",
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS

ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-matroska",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "audio/m4a",
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/octet-stream",  # browsers often send this for MKV/MOV; validated by sniffing
}

DEFAULT_FILLER_WORDS = (
    "um",
    "uh",
    "erm",
    "hmm",
    "like",
    "you know",
    "basically",
    "actually",
    "literally",
    "sort of",
    "kind of",
    "i mean",
)
