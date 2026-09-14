# -*- coding: utf-8 -*-
"""The OAuth providers a user can sign in with.

OAuth is the flow where the browser is sent to Google or Discord, the
user approves, and the provider hands back a token that proves who they
are. Authlib does the protocol; this module reduces each provider to
two operations the routes need — start the redirect, and turn the
callback into an ``Identity`` — so tests can swap in a fake provider
without touching the routes.

A provider is *configured* when both its client id and secret are set
in the environment; the sign-in UI only offers configured providers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

#: Provider name -> (client id variable, client secret variable).
PROVIDER_ENV = {
    "google": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "discord": ("DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"),
}


@dataclass(frozen=True)
class Identity:
    """What a provider tells us about the person who just signed in."""

    provider: str
    #: The provider's stable id for this account (never the email).
    subject: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class OAuthProvider(Protocol):
    name: str

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response: ...

    async def fetch_identity(self, request: Request) -> Identity: ...


def _credentials(name: str) -> Optional[Dict[str, str]]:
    id_var, secret_var = PROVIDER_ENV[name]
    client_id = (os.getenv(id_var) or "").strip()
    client_secret = (os.getenv(secret_var) or "").strip()
    if not client_id or not client_secret:
        return None
    return {"client_id": client_id, "client_secret": client_secret}


def configured_providers() -> List[str]:
    """Providers with both credentials set, in display order."""
    return [name for name in PROVIDER_ENV if _credentials(name) is not None]


def _google_identity(client: Any, token: Dict[str, Any], _request: Request) -> Identity:
    info = token.get("userinfo") or {}
    return Identity(
        provider="google",
        subject=str(info.get("sub") or ""),
        email=info.get("email"),
        display_name=info.get("name"),
        avatar_url=info.get("picture"),
    )


async def _discord_identity(client: Any, token: Dict[str, Any], _request: Request) -> Identity:
    response = await client.get("users/@me", token=token)
    profile = response.json()
    user_id = str(profile.get("id") or "")
    avatar_hash = profile.get("avatar")
    return Identity(
        provider="discord",
        subject=user_id,
        email=profile.get("email"),
        display_name=profile.get("global_name") or profile.get("username"),
        avatar_url=(
            f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png"
            if user_id and avatar_hash else None
        ),
    )


class AuthlibProvider:
    """One registered Authlib client plus the profile-to-identity step."""

    def __init__(self, name: str, client: Any, identity: Callable[..., Any]) -> None:
        self.name = name
        self._client = client
        self._identity = identity

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._client.authorize_redirect(request, redirect_uri)

    async def fetch_identity(self, request: Request) -> Identity:
        token = await self._client.authorize_access_token(request)
        result = self._identity(self._client, token, request)
        if hasattr(result, "__await__"):
            result = await result
        if not result.subject:
            raise HTTPException(
                status_code=502,
                detail={"error": "auth_failed",
                        "message": f"{self.name} returned no account id"},
            )
        return result


_registry: Any = None


def _oauth_registry() -> Any:
    """Authlib's client registry, built once from the environment."""
    global _registry
    if _registry is not None:
        return _registry
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    google = _credentials("google")
    if google:
        oauth.register(
            name="google",
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
            **google,
        )
    discord = _credentials("discord")
    if discord:
        oauth.register(
            name="discord",
            authorize_url="https://discord.com/api/oauth2/authorize",
            access_token_url="https://discord.com/api/oauth2/token",
            api_base_url="https://discord.com/api/",
            client_kwargs={"scope": "identify email"},
            **discord,
        )
    _registry = oauth
    return oauth


_IDENTITY_STEPS = {"google": _google_identity, "discord": _discord_identity}


def get_provider(name: str) -> OAuthProvider:
    """The provider for a sign-in route; 404 unknown, 503 unconfigured.
    Module-level on purpose — tests replace it with a fake."""
    if name not in PROVIDER_ENV:
        raise HTTPException(
            status_code=404,
            detail={"error": "unknown_provider",
                    "message": f"no sign-in provider named {name!r}"},
        )
    if _credentials(name) is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "provider_not_configured",
                    "message": f"{name} sign-in is not configured on this server"},
        )
    client = _oauth_registry().create_client(name)
    return AuthlibProvider(name, client, _IDENTITY_STEPS[name])


def reset_registry() -> None:
    """Test helper: forget the registry so a changed environment is re-read."""
    global _registry
    _registry = None
