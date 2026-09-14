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


@dataclass(frozen=True)
class ModelChoice:
    id: str
    label: str
    provider: str
    provider_label: str
    key_url: str


#: The curated list. ``id`` is the litellm model string.
MODEL_CATALOG: List[ModelChoice] = [
    ModelChoice("gemini/gemini-2.5-flash", "Gemini 2.5 Flash", "gemini",
                "Google Gemini", "https://aistudio.google.com/apikey"),
    ModelChoice("gemini/gemini-2.5-pro", "Gemini 2.5 Pro", "gemini",
                "Google Gemini", "https://aistudio.google.com/apikey"),
    ModelChoice("openai/gpt-4o-mini", "GPT-4o mini", "openai",
                "OpenAI", "https://platform.openai.com/api-keys"),
    ModelChoice("openai/gpt-4o", "GPT-4o", "openai",
                "OpenAI", "https://platform.openai.com/api-keys"),
    ModelChoice("deepseek/deepseek-chat", "DeepSeek Chat", "deepseek",
                "DeepSeek", "https://platform.deepseek.com/api_keys"),
]

#: Data-source keys a user may override, in display order.
DATA_KEY_NAMES = tuple(DATA_KEY_ENV)

_MASK_VISIBLE = 4


def catalog() -> List[Dict[str, str]]:
    return [choice.__dict__.copy() for choice in MODEL_CATALOG]


def model_choice(model_id: str) -> ModelChoice:
    for choice in MODEL_CATALOG:
        if choice.id == model_id:
            return choice
    raise UnknownModel(f"{model_id!r} is not on the model list")


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
        "llm_model": getattr(row, "llm_model", None) if row is not None else None,
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


def save_user_settings(
    user_id: int,
    llm_model: Any = _UNCHANGED,
    llm_api_key: Any = _UNCHANGED,
    finnhub_api_key: Any = _UNCHANGED,
    alphavantage_api_key: Any = _UNCHANGED,
    fred_api_key: Any = _UNCHANGED,
) -> Dict[str, Any]:
    """Update the given fields; omitted ones stay. A key given as an
    empty string is cleared. Returns the masked view."""
    from src.storage import UserSettingsRecord, utc_naive_now

    if llm_model is not _UNCHANGED and llm_model:
        model_choice(str(llm_model))  # raises UnknownModel

    updates: Dict[str, Any] = {}
    if llm_model is not _UNCHANGED:
        updates["llm_model"] = (str(llm_model).strip() or None) if llm_model else None
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
            llm_model=row.llm_model or None,
            llm_api_key=decrypt_secret(row.llm_api_key_enc),
            data_keys=data_keys,
        )
