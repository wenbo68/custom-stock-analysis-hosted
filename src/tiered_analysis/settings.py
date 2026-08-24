# -*- coding: utf-8 -*-
"""User sizing settings for tiered analysis (v2 slice 6).

Sizing is opt-in: the share formula only runs when the user has said how
much capital they trade with and what fraction of it they accept losing
on one trade. The values live in the product's existing settings
mechanism — ``.env`` keys, editable from the web settings page — and
absent settings keep v1 behavior (no share counts, ever).

Parsing is fail-loud: a malformed value never silently becomes a number;
it is dropped with a warning and sizing stays off (a missing number is
safer than a fake one).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import List, Mapping, Optional, Tuple

ENV_CAPITAL = "TIERED_SIZING_CAPITAL"
ENV_RISK_FRACTION = "TIERED_SIZING_RISK_FRACTION"
ENV_REWARD_RISK = "TIERED_SIZING_REWARD_RISK"

#: The reward-to-risk ratio the target aims for (target = entry + R × risk).
#: A resistance-capped target below this ratio draws a warning; the 1.5
#: hard floor in levels.py still voids the plan outright.
DEFAULT_REWARD_RISK = 2.0


@dataclass(frozen=True)
class SizingSettings:
    """What the sizing engine needs from the user, plus parse warnings."""

    capital: Optional[float] = None
    risk_fraction: Optional[float] = None
    #: Shares of this stock the user already holds. Per-run input only (a
    #: holding is stock-specific, so an .env default makes no sense);
    #: 0 = none, which keeps every pre-ownership behavior unchanged.
    ownership: int = 0
    #: Target reward-to-risk ratio the user asks the plan for.
    reward_risk: float = DEFAULT_REWARD_RISK
    warnings: Tuple[str, ...] = ()

    @property
    def is_enabled(self) -> bool:
        return self.capital is not None and self.risk_fraction is not None


def _parse_optional(
    env: Mapping[str, str], key: str, warnings: List[str]
) -> Optional[float]:
    raw = (env.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        warnings.append(f"{key}={raw!r} is not a number — ignored")
        return None


def load_sizing_settings(env: Optional[Mapping[str, str]] = None) -> SizingSettings:
    """Read sizing settings from the environment (``.env``-backed)."""
    if env is None:
        env = os.environ
    warnings: List[str] = []

    capital = _parse_optional(env, ENV_CAPITAL, warnings)
    risk_fraction = _parse_optional(env, ENV_RISK_FRACTION, warnings)

    reward = _parse_optional(env, ENV_REWARD_RISK, warnings)
    if reward is None or reward <= 1.0:
        if reward is not None:
            warnings.append(
                f"{ENV_REWARD_RISK}={reward:g} must be above 1 — using the "
                f"default {DEFAULT_REWARD_RISK:g}"
            )
        reward = DEFAULT_REWARD_RISK

    # Range sanity lives in the sizing engine (single source of refusal
    # reasons); here we only guarantee "number or absent".
    return SizingSettings(
        capital=capital,
        risk_fraction=risk_fraction,
        reward_risk=reward,
        warnings=tuple(warnings),
    )


#: Every run sizes (owner decision 2026-07-24): when neither the request
#: nor the saved .env settings provide capital/risk, these — the web
#: form's own defaults (100k capital, 1% risk) — fill in, so the API and
#: scripted runs behave like a form submission. Precedence stays:
#: per-run override > saved .env setting > this fallback.
FALLBACK_CAPITAL = 100_000.0
FALLBACK_RISK_FRACTION = 0.01


def with_fallback_defaults(settings: SizingSettings) -> SizingSettings:
    """A copy with the web-form fallback filling any missing sizing input."""
    return replace(
        settings,
        capital=settings.capital if settings.capital is not None else FALLBACK_CAPITAL,
        risk_fraction=(
            settings.risk_fraction
            if settings.risk_fraction is not None
            else FALLBACK_RISK_FRACTION
        ),
    )


def merge_overrides(
    settings: SizingSettings,
    capital: Optional[float] = None,
    risk_fraction: Optional[float] = None,
    ownership: Optional[float] = None,
    reward_risk: Optional[float] = None,
) -> SizingSettings:
    """Per-run overrides (from the API request) on top of saved settings.

    Returns a new object — settings are never mutated in place.
    """
    merged = settings
    if capital is not None:
        merged = replace(merged, capital=float(capital))
    if risk_fraction is not None:
        merged = replace(merged, risk_fraction=float(risk_fraction))
    if ownership is not None and int(ownership) >= 0:
        merged = replace(merged, ownership=int(ownership))
    if reward_risk is not None and float(reward_risk) > 1.0:
        merged = replace(merged, reward_risk=float(reward_risk))
    return merged
