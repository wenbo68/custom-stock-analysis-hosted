# -*- coding: utf-8 -*-
"""Sign-in routes: which providers exist, start a login, finish it,
sign out, and "who am I". Mounted under /api/auth."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from api.auth import providers, session
from src.users import upsert_from_identity

logger = logging.getLogger(__name__)

router = APIRouter()

#: Where the browser lands after a finished (or failed) sign-in.
AFTER_LOGIN_PATH = "/"
LOGIN_FAILED_PATH = "/?login=failed"


def _callback_url(request: Request, provider: str) -> str:
    """The URL the provider sends the browser back to. ``PUBLIC_BASE_URL``
    wins when set (a proxy in front may hide the real scheme/host);
    otherwise the request's own URL for the callback route."""
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}/api/auth/callback/{provider}"
    return str(request.url_for("auth_callback", provider=provider))


@router.get("/providers")
def list_providers() -> Dict[str, List[str]]:
    """Providers a user can sign in with on this server."""
    return {"providers": providers.configured_providers()}


@router.get("/login/{provider}")
async def auth_login(request: Request, provider: str):
    """Send the browser to the provider's consent screen."""
    client = providers.get_provider(provider)
    return await client.authorize_redirect(request, _callback_url(request, provider))


@router.get("/callback/{provider}", name="auth_callback")
async def auth_callback(request: Request, provider: str):
    """The provider sent the browser back: turn the callback into an
    identity, create or refresh the user row, start the session."""
    client = providers.get_provider(provider)
    try:
        identity = await client.fetch_identity(request)
    except Exception as exc:  # denied consent, expired state, provider down
        logger.warning("%s sign-in failed: %s", provider, exc)
        return RedirectResponse(LOGIN_FAILED_PATH, status_code=303)
    user = upsert_from_identity(identity)
    session.sign_in(request, user["id"])
    return RedirectResponse(AFTER_LOGIN_PATH, status_code=303)


@router.post("/logout")
def auth_logout(request: Request) -> Dict[str, bool]:
    session.sign_out(request)
    return {"ok": True}


@router.get("/me")
def auth_me(user: Optional[Dict[str, Any]] = Depends(session.optional_user)) -> Dict[str, Any]:
    return {"user": user}
