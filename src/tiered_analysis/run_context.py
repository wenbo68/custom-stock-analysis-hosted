# -*- coding: utf-8 -*-
"""Per-run settings: which model answers, whose key pays, which data keys
the report cards may use.

On the public server every run belongs to a signed-in user who brings
their own LLM key and may bring their own data-source keys. Those must
never be written into the process environment — every concurrent run
would see them — so they ride on the run's ``LlmUsageTracker``, which
the engine already activates per run and re-activates inside its worker
threads. The accessors below read the active run's settings first and
fall back to the environment (local CLI runs, tests).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

#: Data-source key name -> the environment variable it falls back to.
DATA_KEY_ENV: Dict[str, str] = {
    "finnhub": "FINNHUB_API_KEY",
    "alphavantage": "ALPHAVANTAGE_API_KEY",
    "fred": "FRED_API_KEY",
}


@dataclass(frozen=True)
class RunSettings:
    """What one run may use. Empty fields fall back to the environment."""

    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    data_keys: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_llm_configured(self) -> bool:
        return bool(self.llm_model and self.llm_api_key)


def active_run_settings() -> RunSettings:
    """The settings of the run on this thread (empty outside a run)."""
    from .llm_support import active_tracker

    tracker = active_tracker()
    settings = getattr(tracker, "settings", None) if tracker is not None else None
    return settings if settings is not None else RunSettings()


def llm_model() -> Optional[str]:
    """The run's model, else ``LITELLM_MODEL``."""
    model = active_run_settings().llm_model or os.getenv("LITELLM_MODEL") or ""
    return model.strip() or None


def llm_api_key() -> Optional[str]:
    """The run's own LLM key, or None to let litellm read the provider's
    standard environment variable."""
    key = (active_run_settings().llm_api_key or "").strip()
    return key or None


def data_key(name: str) -> Optional[str]:
    """A data-source key: the run's own first, the server's environment
    default second, None when neither is set."""
    if name not in DATA_KEY_ENV:
        raise KeyError(f"unknown data key {name!r}")
    own = (active_run_settings().data_keys.get(name) or "").strip()
    if own:
        return own
    fallback = (os.getenv(DATA_KEY_ENV[name]) or "").strip()
    return fallback or None
