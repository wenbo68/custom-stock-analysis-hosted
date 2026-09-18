# -*- coding: utf-8 -*-
"""The signed session cookie and the "who is calling" dependencies.

After sign-in the server stores only the user id in a cookie signed with
``AUTH_SECRET`` (Starlette's SessionMiddleware, backed by
itsdangerous). Signed means the server can tell the cookie was not
tampered with; HttpOnly means page scripts cannot read it; SameSite=Lax
means other sites cannot ride it on cross-site POSTs, which is the
app's CSRF protection together with the narrowed CORS policy.
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

SESSION_COOKIE = "csa_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600
_SESSION_USER_KEY = "user_id"


def session_secret() -> str:
    """``AUTH_SECRET`` from the environment. A missing secret gets a
    random one (every restart signs everyone out) with a loud warning —
    fine on a laptop, wrong on the public host."""
    secret = (os.getenv("AUTH_SECRET") or "").strip()
    if secret:
        return secret
    logger.warning(
        "AUTH_SECRET is not set — using a random secret; every restart "
        "signs all users out. Set it on the public host."
    )
    return secrets.token_urlsafe(48)


def cookie_is_https_only() -> bool:
    """Send the cookie over HTTPS only when hosted (the platform passes
    PORT) unless SESSION_COOKIE_SECURE says otherwise."""
    explicit = (os.getenv("SESSION_COOKIE_SECURE") or "").strip().lower()
    if explicit in ("true", "false"):
        return explicit == "true"
    return bool(os.getenv("PORT"))


def sign_in(request: Request, user_id: int) -> None:
    request.session.clear()
    request.session[_SESSION_USER_KEY] = int(user_id)


def sign_out(request: Request) -> None:
    request.session.clear()


def optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """The signed-in user, or None."""
    from src.users import get_user

    user_id = request.session.get(_SESSION_USER_KEY) if "session" in request.scope else None
    if user_id is None:
        return None
    user = get_user(int(user_id))
    if user is None:  # a deleted account with a still-valid cookie
        request.session.clear()
    return user


def current_user(request: Request) -> Dict[str, Any]:
    """The signed-in user, or 401."""
    user = optional_user(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "sign in to continue"},
        )
    return user
