"""Centralised settings loaded from environment variables (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AIProviderName = Literal["openai", "anthropic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_env: Literal["development", "production", "test"] = "development"
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    cors_origins: str = ""  # comma-separated extra origins (e.g. Vercel preview URLs)
    log_level: str = "INFO"

    # Database / cache
    database_url: str = "postgresql+psycopg://cutpilot:cutpilot@localhost:5432/cutpilot"
    redis_url: str = "redis://localhost:6379/0"
    # Optional PostgreSQL schema to isolate CutPilot tables in a shared database (e.g. Supabase).
    db_schema: str | None = None

    # Auth
    jwt_secret: str = Field(default="dev-only-secret-change-me", min_length=16)
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None

    # AI providers
    ai_provider: AIProviderName = "openai"
    ai_fallback_provider: AIProviderName | None = "anthropic"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_planner_model: str = "gpt-4o"
    openai_vision_model: str = "gpt-4o"
    openai_transcription_model: str = "whisper-1"
    anthropic_planner_model: str = "claude-opus-5"
    anthropic_vision_model: str = "claude-opus-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    ai_max_retries: int = 2
    ai_request_timeout_seconds: int = 120

    # Local AI adapters
    local_transcription_enabled: bool = False
    transcription_provider: Literal["openai", "whisperx", "faster_whisper"] = "openai"
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    local_diarization_enabled: bool = False
    hf_token: str | None = None
    local_vision_enabled: bool = False

    # Storage
    storage_provider: Literal["local", "s3"] = "local"
    local_storage_root: str = "./data/storage"
    s3_endpoint: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "cutpilot"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_signed_url_ttl_seconds: int = 3600
    s3_force_path_style: bool = True

    # Media
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    max_upload_size: int = 10 * 1024**3
    upload_chunk_size: int = 8 * 1024**2
    proxy_height: int = 720
    proxy_video_bitrate: str = "2500k"
    work_dir: str = "./data/work"

    # Rate limiting
    rate_limit_per_minute: int = 120
    ai_rate_limit_per_minute: int = 20

    @field_validator("db_schema", mode="before")
    @classmethod
    def _schema_empty_to_none(cls, value: object) -> object:
        if value in ("", None):
            return None
        if isinstance(value, str) and not value.replace("_", "").isalnum():
            raise ValueError("DB_SCHEMA must be alphanumeric/underscore")
        return value

    @field_validator("ai_fallback_provider", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if value in ("", None):
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        """SQLAlchemy URL for synchronous engines (workers, alembic)."""
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        if url.startswith("sqlite+aiosqlite://"):
            return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
        return url

    @property
    def async_database_url(self) -> str:
        """SQLAlchemy URL for the async engine used by the API."""
        url = self.database_url
        if url.startswith("postgresql+psycopg://"):
            return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("sqlite://") and "aiosqlite" not in url:
            return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return url

    def provider_key(self, provider: AIProviderName) -> str | None:
        return self.openai_api_key if provider == "openai" else self.anthropic_api_key

    def planner_model(self, provider: AIProviderName) -> str:
        return self.openai_planner_model if provider == "openai" else self.anthropic_planner_model

    def vision_model(self, provider: AIProviderName) -> str:
        return self.openai_vision_model if provider == "openai" else self.anthropic_vision_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
