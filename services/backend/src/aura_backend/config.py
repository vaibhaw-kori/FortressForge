"""Typed configuration loaded from environment variables.

Pydantic-settings validates all values at boot; the application refuses
to start with invalid config.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="AURA_",
    )

    env: str = "dev"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    database_url: str = "sqlite:///./data/aura.db"
    redis_url: str = "redis://localhost:6379/0"
    queue_enabled: bool = False

    s3_endpoint: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_captures: str = "aura-captures"
    s3_bucket_assets: str = "aura-assets"
    s3_bucket_generated: str = "aura-generated"
    s3_bucket_thumbnails: str = "aura-thumbnails"
    s3_public_base_url: str = "http://localhost:9000"

    runpod_api_key: str = ""
    runpod_endpoint_fake: str = "fake"
    runpod_endpoint_svd: str = ""
    runpod_endpoint_animatediff: str = ""
    runpod_provider_default: str = "mock"

    # Wan 2.1 local inference settings
    wan_provider_enabled: bool = False
    wan_model_variant: str = "wan2.1-i2v-14b-720p"
    wan_precision: str = "bf16"
    wan_model_repo: str = "Wan-AI/Wan2.1-I2V-14B-720P"
    wan_local_model_path: str = ""
    wan_enable_offload: bool = False
    wan_offload_to_cpu: bool = False
    wan_enable_vae_tiling: bool = True
    wan_vae_tile_size: int = 512
    wan_enable_xformers: bool = True
    wan_enable_flash_attention: bool = True
    wan_compile_transformer: bool = False
    wan_compile_vae: bool = False
    wan_device: str = "cuda"
    wan_dtype: str = "bfloat16"

    inference_warmup_on_boot: bool = False

    generation_timeout_ms: int = 300_000
    generation_max_attempts: int = 2

    operator_jwt_secret: str = "change-me-in-prod"
    operator_jwt_ttl_sec: int = 900
    kiosk_token_default: str = "kiosk-dev-token"
    storage_signing_secret: str = "change-me-storage-signing-secret"
    storage_signed_url_ttl_sec: int = 3600  # 1 hour
    retention_captures_days: int = 7
    retention_generated_days: int = 30
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 20

    reel_policy_json: str = (
        '{"insertMode":"fifo","maxGeneratedInQueue":3,'
        '"minGapBetweenGeneratedSeconds":60,"percentageOfReelForGenerated":30}'
    )

    cors_allow_origins: str = (
        "http://localhost:5173,http://localhost:5174,http://localhost:5175"
    )

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        return v.upper()

    def validate_secrets(self) -> list[str]:
        """Return list of insecure defaults that must be changed in prod."""
        warnings: list[str] = []
        if self.env == "prod":
            if self.operator_jwt_secret == "change-me-in-prod":
                warnings.append("AURA_OPERATOR_JWT_SECRET is insecure default")
            if self.storage_signing_secret == "change-me-storage-signing-secret":
                warnings.append("AURA_STORAGE_SIGNING_SECRET is insecure default")
            if self.kiosk_token_default == "kiosk-dev-token":
                warnings.append("AURA_KIOSK_TOKEN_DEFAULT is insecure default")
            if not self.runpod_api_key and "runpod" in self.runpod_provider_default:
                warnings.append("AURA_RUNPOD_API_KEY missing for RunPod provider")
        return warnings

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def reel_policy(self) -> dict[str, Any]:
        try:
            return json.loads(self.reel_policy_json)
        except json.JSONDecodeError:
            return {}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def data_dir(self) -> Path:
        # Resolve relative to the backend package root so CWD at launch does not matter
        # (prevents restart-from-different-CWD from creating a second DB file).
        from pathlib import Path as _P

        # .../services/backend/src/aura_backend/config.py -> .../services/backend
        backend_root = _P(__file__).resolve().parents[2]
        p = backend_root / "data"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def resolved_database_url(self) -> str:
        """Return database URL with absolute path for sqlite so restarts are DB-stable."""
        if self.is_sqlite and self.database_url.startswith("sqlite:///./"):
            rel = self.database_url[len("sqlite:///./") :]
            abs_path = (self.data_dir / rel.replace("data/", "")).resolve() if rel.startswith("data/") else (self.data_dir.parent / rel).resolve()
            # keep sqlite:///<abs> form (4 slashes on Windows)
            return f"sqlite:///{abs_path.as_posix()}"
        if self.is_sqlite and self.database_url.startswith("sqlite:///"):
            # already absolute-ish, leave as is
            return self.database_url
        return self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()


def reset_settings_cache() -> None:
    """Test helper: clear the cached settings instance."""
    get_settings.cache_clear()