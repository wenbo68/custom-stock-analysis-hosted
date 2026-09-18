# -*- coding: utf-8 -*-
"""The signed-in user's keys and model choice. Mounted under
/api/v1/settings. Keys come back masked; the decrypted values only ever
travel inside a run."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth.session import current_user
from src import user_settings

router = APIRouter()


class SettingsUpdate(BaseModel):
    """Every field optional: absent = unchanged, "" = clear the key."""

    llm_model: Optional[str] = Field(default=None, max_length=128)
    llm_sub_model: Optional[str] = Field(default=None, max_length=128)
    llm_api_key: Optional[str] = Field(default=None, max_length=512)
    finnhub_api_key: Optional[str] = Field(default=None, max_length=512)
    alphavantage_api_key: Optional[str] = Field(default=None, max_length=512)
    fred_api_key: Optional[str] = Field(default=None, max_length=512)


def _with_catalog(view: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **view,
        "models": user_settings.catalog(),
        "defaults": user_settings.provider_defaults(),
    }


@router.get("/me")
def get_my_settings(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    try:
        return _with_catalog(user_settings.load_user_settings(user["id"]))
    except user_settings.EncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail={
            "error": "encryption_not_configured", "message": str(exc)})


@router.put("/me")
def update_my_settings(
    update: SettingsUpdate, user: Dict[str, Any] = Depends(current_user)
) -> Dict[str, Any]:
    fields = update.model_dump(exclude_unset=True)
    try:
        return _with_catalog(user_settings.save_user_settings(user["id"], **fields))
    except user_settings.UnknownModel as exc:
        raise HTTPException(status_code=422, detail={
            "error": "unknown_model", "message": str(exc)})
    except user_settings.ModelMismatch as exc:
        raise HTTPException(status_code=422, detail={
            "error": "model_mismatch", "message": str(exc)})
    except user_settings.EncryptionNotConfigured as exc:
        raise HTTPException(status_code=503, detail={
            "error": "encryption_not_configured", "message": str(exc)})
