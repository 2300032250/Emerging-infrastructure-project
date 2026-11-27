"""Versioned configuration and startup validation (Section 5.3 & NT-5)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised when configuration is unversioned, invalid, or violates trust boundaries (NT-5)."""


class Settings(BaseSettings):
    """Application settings validated at startup and hashed into every assessment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Emerging Infrastructure Project Maturity Assessment"
    use_case_id: str = "CLOUD-225"
    team_batch: str = "C2C-95"

    database_url: str = Field(default="sqlite:///./data/maturity.db")
    config_version: str = Field(default="1.0.0")
    stall_horizon_months: int = Field(default=12, ge=1, le=36)
    observation_window_months: int = Field(default=12, ge=3, le=36)
    model_seed: int = Field(default=42)
    cutoff_date: str = Field(default="2025-11-01")

    github_token: Optional[str] = Field(default=None)
    github_timeout_seconds: float = Field(default=10.0, gt=0.0, le=60.0)

    degraded_mode: bool = Field(default=False)
    require_pinned_deps: bool = Field(default=True)
    popularity_fields_excluded: bool = Field(default=True)

    @field_validator("config_version")
    @classmethod
    def check_semver(cls, v: str) -> str:
        if not v or not re.match(r"^\d+\.\d+\.\d+$", v.strip()):
            raise ValueError("config_version must be a valid semantic version (e.g. 1.0.0)")
        return v.strip()

    @field_validator("popularity_fields_excluded")
    @classmethod
    def check_popularity_excluded(cls, v: bool) -> bool:
        if not v:
            raise ValueError("popularity_fields_excluded cannot be False (NT-1 / NT-3 policy)")
        return v

    @property
    def config_hash(self) -> str:
        """Deterministic SHA-256 hash of versioned analytical & security settings."""
        payload = {
            "config_version": self.config_version,
            "stall_horizon_months": self.stall_horizon_months,
            "observation_window_months": self.observation_window_months,
            "model_seed": self.model_seed,
            "cutoff_date": self.cutoff_date,
            "popularity_fields_excluded": self.popularity_fields_excluded,
            "require_pinned_deps": self.require_pinned_deps,
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]


def validate_dependency_pinning(requirements_path: Optional[Path] = None) -> tuple[bool, list[str]]:
    """Verify all dependencies in requirements.txt are strictly pinned (==) for NT-5."""
    path = requirements_path or (Path(__file__).resolve().parent.parent / "requirements.txt")
    if not path.exists():
        return False, ["requirements.txt missing"]
    unpinned: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            unpinned.append(line)
    return len(unpinned) == 0, unpinned


def validate_startup_config(settings: Settings, requirements_path: Optional[Path] = None) -> None:
    """Refuse startup if config is invalid, unversioned, or dependencies drifted (Section 5.3, NT-5)."""
    if not settings.popularity_fields_excluded:
        raise ConfigurationError("NT-1/NT-3 violation: popularity fields must remain excluded.")
    if settings.require_pinned_deps:
        pinned_ok, unpinned = validate_dependency_pinning(requirements_path)
        if not pinned_ok:
            raise ConfigurationError(f"NT-5 dependency drift detected: unpinned entries {unpinned}")


settings = Settings()
