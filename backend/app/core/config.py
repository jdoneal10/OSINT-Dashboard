"""Application settings, loaded from environment variables (prefix ``OSINT_``) and ``.env``.

Secrets do not live here; see :mod:`app.core.secrets`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OSINT_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "ci"] = "dev"
    database_url: str = "postgresql+psycopg://osint:osint@127.0.0.1:5432/osint"
    test_database_url: str = "postgresql+psycopg://osint:osint@127.0.0.1:5432/osint_test"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    log_level: str = "INFO"

    # Phase 2+: enforced against the llm_usage table.
    llm_monthly_budget_usd: float = 75.0
    llm_budget_alert_fraction: float = 0.8

    worker_heartbeat_minutes: int = 5

    repo_root: Path = REPO_ROOT
    # Raw source snapshots (gitignored). Overridable so tests never write into the repo.
    data_raw_dir: Path = REPO_ROOT / "data" / "raw"

    @property
    def reference_dir(self) -> Path:
        return self.repo_root / "data" / "reference"

    @property
    def raw_dir(self) -> Path:
        return self.data_raw_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
