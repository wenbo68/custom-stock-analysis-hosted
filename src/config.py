# -*- coding: utf-8 -*-
"""Slim configuration for the standalone tiered-analysis app.

The parent project's config module is ~3.4k lines of whole-app settings
(notifications, bots, scheduling, ...). This app only needs the fields
actually read by the copied modules:

- ``src/storage.py``   -> database path + sqlite tuning knobs
- ``data_provider/``   -> data-source feature flags, timeouts, optional
                          vendor API keys (all keys optional; a missing
                          key just skips that fallback source)

Everything else the tiered engine reads (LITELLM_MODEL, FINNHUB_API_KEY,
FRED_API_KEY, ALPHAVANTAGE_API_KEY, NEWS_SCREEN_MODEL, TIERED_* sizing
defaults) is read straight from the environment by the engine itself, so
it does not appear here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() == 'true'


def _env_int(name: str, default: int, minimum: Optional[int] = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None and raw.strip() else default
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw is not None and raw.strip() else default
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str = '') -> Optional[str]:
    value = (os.getenv(name) or default).strip()
    return value or None


def _normalize_database_url(url: str) -> str:
    """Hosted Postgres (Neon, Railway, ...) hands out ``postgres://`` or
    ``postgresql://`` URLs; SQLAlchemy needs the driver spelled out."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass
class Config:
    # --- database (read by src/storage.py DatabaseManager) ---
    #: Full connection URL (Postgres on the public host). When set it wins
    #: over DATABASE_PATH, which stays the local sqlite default.
    database_url: Optional[str] = field(
        default_factory=lambda: _env_str('DATABASE_URL'))
    database_path: str = field(
        default_factory=lambda: os.getenv('DATABASE_PATH', './data/stock_analysis.db'))
    sqlite_wal_enabled: bool = field(
        default_factory=lambda: _env_bool('SQLITE_WAL_ENABLED', True))
    sqlite_busy_timeout_ms: int = field(
        default_factory=lambda: _env_int('SQLITE_BUSY_TIMEOUT_MS', 5000, minimum=0))

    # --- data vendor keys (missing key = that source is skipped) ---
    finnhub_api_key: Optional[str] = field(
        default_factory=lambda: _env_str('FINNHUB_API_KEY'))
    alphavantage_api_key: Optional[str] = field(
        default_factory=lambda: _env_str('ALPHAVANTAGE_API_KEY'))

    def get_db_url(self) -> str:
        """SQLAlchemy URL: DATABASE_URL when set (Postgres), else the
        sqlite file at DATABASE_PATH (its directory is created)."""
        if self.database_url:
            return _normalize_database_url(self.database_url)
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f'sqlite:///{db_path.absolute()}'

    @classmethod
    def reset_instance(cls) -> None:
        """Parity with the parent project's Config singleton API (tests
        call Config.reset_instance() to force a re-read of the env)."""
        reset_config()


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """Test helper: force the next get_config() to re-read the environment."""
    global _config
    _config = None
