# -*- coding: utf-8 -*-
"""Each user's own keys and model choice (the ``user_settings`` table).

Keys are encrypted at rest with Fernet (symmetric: one server secret,
``APP_ENCRYPTION_KEY``, both locks and unlocks) and only ever shown back
masked. The model comes from a short curated list: the prompts were
tuned on these, structured-output support is known for them, and the
key must match the model's provider.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.tiered_analysis.run_context import DATA_KEY_ENV, RunSettings


class EncryptionNotConfigured(RuntimeError):
    """``APP_ENCRYPTION_KEY`` is missing or malformed."""


class UnknownModel(ValueError):
    """The model is not on the curated list."""


class ModelMismatch(ValueError):
    """The main and sub models belong to different providers — one key
    cannot pay for both."""


@dataclass(frozen=True)
class ModelChoice:
    id: str
    label: str
    provider: str
    provider_label: str
    key_url: str


#: The curated list, strongest first within each provider. ``id`` is
#: the litellm model string. Refreshed September 2026: Gemini 2.5 retires
#: mid-October 2026, GPT-4o is two generations old, and DeepSeek now
#: documents only ``deepseek-v4-pro`` and ``deepseek-flash``.
_GEMINI = ("gemini", "Google Gemini", "https://aistudio.google.com/apikey")
_OPENAI = ("openai", "OpenAI", "https://platform.openai.com/api-keys")
_DEEPSEEK = ("deepseek", "DeepSeek", "https://platform.deepseek.com/api_keys")

MODEL_CATALOG: List[ModelChoice] = [
    ModelChoice("gemini/gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)", *_GEMINI),
    ModelChoice("gemini/gemini-3.8-flash", "Gemini 3.8 Flash", *_GEMINI),
    ModelChoice("gemini/gemini-3.7-flash", "Gemini 3.7 Flash", *_GEMINI),
    ModelChoice("gemini/gemini-3.6-flash", "Gemini 3.6 Flash", *_GEMINI),
    ModelChoice("gemini/gemini-3.5-flash", "Gemini 3.5 Flash", *_GEMINI),
    ModelChoice("gemini/gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", *_GEMINI),
    ModelChoice("gemini/gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", *_GEMINI),
    ModelChoice("openai/gpt-6-astra", "GPT-6 Astra", *_OPENAI),
    ModelChoice("openai/gpt-5.6-sol", "GPT-5.6 Sol", *_OPENAI),
    ModelChoice("openai/gpt-5.6-terra", "GPT-5.6 Terra", *_OPENAI),
    ModelChoice("openai/gpt-5.6-luna", "GPT-5.6 Luna", *_OPENAI),
    ModelChoice("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", *_DEEPSEEK),
    ModelChoice("deepseek/deepseek-flash", "DeepSeek Flash", *_DEEPSEEK),
]

#: Data-source keys a user may override, in display order.
DATA_KEY_NAMES = tuple(DATA_KEY_ENV)

_MASK_VISIBLE = 4


def catalog() -> List[Dict[str, str]]:
    return [choice.__dict__.copy() for choice in MODEL_CATALOG]


def model_rank(model_id: Optional[str]) -> Optional[int]:
    """Position on the curated list (0 = strongest of its provider), or
    None for a retired or unknown id."""
    for rank, choice in enumerate(MODEL_CATALOG):
        if choice.id == model_id:
            return rank
    return None


def covers_model(source_model: Optional[str], requested_model: Optional[str]) -> bool:
    """Whether an outlook produced by ``source_model`` may stand in for
    one the user asked ``requested_model`` for: same provider, and the
    source is the same model or a stronger one on the curated list
    (which is ordered strongest-first within each provider). A retired
    or unknown model on either side never qualifies."""
    source_rank = model_rank(source_model)
    requested_rank = model_rank(requested_model)
    if source_rank is None or requested_rank is None:
        return False
    if MODEL_CATALOG[source_rank].provider != MODEL_CATALOG[requested_rank].provider:
        return False
    return source_rank <= requested_rank


def model_label(model_id: Optional[str]) -> Optional[str]:
    """The display name of a catalog model; None when retired/unknown."""
    rank = model_rank(model_id)
    return MODEL_CATALOG[rank].label if rank is not None else None


def model_choice(model_id: str) -> ModelChoice:
    for choice in MODEL_CATALOG:
        if choice.id == model_id:
            return choice
    raise UnknownModel(f"{model_id!r} is not on the model list")


def _listed(model_id: Optional[str]) -> Optional[str]:
    """A stored model id, or None once it has dropped off the catalog —
    a retired model reads back as "not picked" rather than being sent
    to the provider or tripping the same-provider check."""
    if not model_id:
        return None
    return model_id if any(c.id == model_id for c in MODEL_CATALOG) else None


# ---- encryption ----

def _fernet():
    from cryptography.fernet import Fernet

    raw = (os.getenv("APP_ENCRYPTION_KEY") or "").strip()
    if not raw:
        raise EncryptionNotConfigured(
            "APP_ENCRYPTION_KEY is not set; the server cannot store keys"
        )
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception as exc:
        raise EncryptionNotConfigured(f"APP_ENCRYPTION_KEY is malformed: {exc}") from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def mask_secret(value: Optional[str]) -> Optional[str]:
    """``••••ab12`` — enough to recognise a key, never enough to use it."""
    if not value:
        return None
    tail = value[-_MASK_VISIBLE:] if len(value) > _MASK_VISIBLE else ""
    return "••••" + tail


# ---- storage ----

def _session():
    from src.storage import DatabaseManager

    return DatabaseManager.get_instance().get_session()


_KEY_COLUMNS = {
    "llm": "llm_api_key_enc",
    "finnhub": "finnhub_key_enc",
    "alphavantage": "alphavantage_key_enc",
    "fred": "fred_key_enc",
}


def _view(row: Any) -> Dict[str, Any]:
    """The masked shape the API hands to the browser."""
    def key_view(column: str) -> Dict[str, Any]:
        token = getattr(row, column, None) if row is not None else None
        secret = decrypt_secret(token) if token else None
        return {"set": bool(secret), "hint": mask_secret(secret)}

    return {
        "llm_model": _listed(getattr(row, "llm_model", None)),
        "llm_sub_model": _listed(getattr(row, "llm_sub_model", None)),
        "llm_api_key": key_view(_KEY_COLUMNS["llm"]),
        "data_keys": {
            name: key_view(_KEY_COLUMNS[name]) for name in DATA_KEY_NAMES
        },
    }


def load_user_settings(user_id: int) -> Dict[str, Any]:
    from src.storage import UserSettingsRecord

    with _session() as session:
        row = session.get(UserSettingsRecord, int(user_id))
        return _view(row)


_UNCHANGED = object()


def _clean_model(value: Any) -> Optional[str]:
    """A model field as stored: the id, or None for empty/cleared."""
    cleaned = (str(value) if value is not None else "").strip()
    if cleaned:
        model_choice(cleaned)  # raises UnknownModel
    return cleaned or None


def _check_same_provider(main: Optional[str], sub: Optional[str]) -> None:
    if main and sub and model_choice(main).provider != model_choice(sub).provider:
        raise ModelMismatch(
            f"{sub!r} is not from the same provider as {main!r}"
        )


def save_user_settings(
    user_id: int,
    llm_model: Any = _UNCHANGED,
    llm_sub_model: Any = _UNCHANGED,
    llm_api_key: Any = _UNCHANGED,
    finnhub_api_key: Any = _UNCHANGED,
    alphavantage_api_key: Any = _UNCHANGED,
    fred_api_key: Any = _UNCHANGED,
) -> Dict[str, Any]:
    """Update the given fields; omitted ones stay. A key or model given
    as an empty string is cleared. Returns the masked view."""
    from src.storage import UserSettingsRecord, utc_naive_now

    updates: Dict[str, Any] = {}
    if llm_model is not _UNCHANGED:
        updates["llm_model"] = _clean_model(llm_model)
    if llm_sub_model is not _UNCHANGED:
        updates["llm_sub_model"] = _clean_model(llm_sub_model)
    for value, column in (
        (llm_api_key, _KEY_COLUMNS["llm"]),
        (finnhub_api_key, _KEY_COLUMNS["finnhub"]),
        (alphavantage_api_key, _KEY_COLUMNS["alphavantage"]),
        (fred_api_key, _KEY_COLUMNS["fred"]),
    ):
        if value is _UNCHANGED:
            continue
        cleaned = (str(value) if value is not None else "").strip()
        updates[column] = encrypt_secret(cleaned) if cleaned else None

    with _session() as session:
        row = session.get(UserSettingsRecord, int(user_id))
        if row is None:
            row = UserSettingsRecord(user_id=int(user_id))
            session.add(row)
        # Checked on the merged result, so a sub model saved on its own
        # still has to match the main model already stored.
        _check_same_provider(
            updates.get("llm_model", _listed(row.llm_model)),
            updates.get("llm_sub_model", _listed(row.llm_sub_model)),
        )
        for column, value in updates.items():
            setattr(row, column, value)
        row.updated_at = utc_naive_now()
        session.commit()
        session.refresh(row)
        return _view(row)


def run_settings_for(user_id: int) -> RunSettings:
    """The decrypted bundle a run carries (never sent to the browser)."""
    from src.storage import UserSettingsRecord

    with _session() as session:
        row = session.get(UserSettingsRecord, int(user_id))
        if row is None:
            return RunSettings()
        data_keys = {}
        for name in DATA_KEY_NAMES:
            secret = decrypt_secret(getattr(row, _KEY_COLUMNS[name]))
            if secret:
                data_keys[name] = secret
        return RunSettings(
            llm_model=_listed(row.llm_model),
            llm_sub_model=_listed(row.llm_sub_model),
            llm_api_key=decrypt_secret(row.llm_api_key_enc),
            data_keys=data_keys,
        )
