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


def _resolve_realtime_source_priority() -> str:
    """Same rule as the parent project: prepend tushare when a token is
    configured but no explicit priority was set."""
    explicit = os.getenv('REALTIME_SOURCE_PRIORITY')
    default_priority = 'tencent,akshare_sina,efinance,akshare_em'
    if explicit:
        return explicit
    if (os.getenv('TUSHARE_TOKEN') or '').strip():
        return f'tushare,{default_priority}'
    return default_priority


@dataclass
class Config:
    # --- database (read by src/storage.py DatabaseManager) ---
    database_path: str = field(
        default_factory=lambda: os.getenv('DATABASE_PATH', './data/stock_analysis.db'))
    sqlite_wal_enabled: bool = field(
        default_factory=lambda: _env_bool('SQLITE_WAL_ENABLED', True))
    sqlite_busy_timeout_ms: int = field(
        default_factory=lambda: _env_int('SQLITE_BUSY_TIMEOUT_MS', 5000, minimum=0))
    sqlite_write_retry_max: int = field(
        default_factory=lambda: _env_int('SQLITE_WRITE_RETRY_MAX', 3, minimum=0))
    sqlite_write_retry_base_delay: float = field(
        default_factory=lambda: _env_float('SQLITE_WRITE_RETRY_BASE_DELAY', 0.1))

    # --- data_provider feature flags / tuning ---
    enable_realtime_quote: bool = field(
        default_factory=lambda: _env_bool('ENABLE_REALTIME_QUOTE', True))
    enable_chip_distribution: bool = field(
        default_factory=lambda: _env_bool('ENABLE_CHIP_DISTRIBUTION', True))
    enable_eastmoney_patch: bool = field(
        default_factory=lambda: _env_bool('ENABLE_EASTMONEY_PATCH', False))
    realtime_source_priority: str = field(
        default_factory=_resolve_realtime_source_priority)
    realtime_cache_ttl: int = field(
        default_factory=lambda: _env_int('REALTIME_CACHE_TTL', 600, minimum=0))
    enable_fundamental_pipeline: bool = field(
        default_factory=lambda: _env_bool('ENABLE_FUNDAMENTAL_PIPELINE', True))
    fundamental_stage_timeout_seconds: float = field(
        default_factory=lambda: _env_float('FUNDAMENTAL_STAGE_TIMEOUT_SECONDS', 8.0))
    fundamental_fetch_timeout_seconds: float = field(
        default_factory=lambda: _env_float('FUNDAMENTAL_FETCH_TIMEOUT_SECONDS', 3.0))
    fundamental_retry_max: int = field(
        default_factory=lambda: _env_int('FUNDAMENTAL_RETRY_MAX', 1, minimum=0))
    fundamental_cache_ttl_seconds: int = field(
        default_factory=lambda: _env_int('FUNDAMENTAL_CACHE_TTL_SECONDS', 120, minimum=0))

    # --- optional vendor keys (missing key = that fallback source is skipped) ---
    tushare_token: Optional[str] = field(
        default_factory=lambda: _env_str('TUSHARE_TOKEN'))
    tickflow_api_key: Optional[str] = field(
        default_factory=lambda: _env_str('TICKFLOW_API_KEY'))
    finnhub_api_key: Optional[str] = field(
        default_factory=lambda: _env_str('FINNHUB_API_KEY'))
    alphavantage_api_key: Optional[str] = field(
        default_factory=lambda: _env_str('ALPHAVANTAGE_API_KEY'))

    def get_db_url(self) -> str:
        """SQLAlchemy sqlite URL; creates the data directory if missing."""
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
