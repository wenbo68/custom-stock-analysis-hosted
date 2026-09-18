# -*- coding: utf-8 -*-
"""Offline tests for sign-in (hosted-app work, 2026-09-14).

The OAuth provider is faked at the seam the routes use
(``api.auth.providers.get_provider``): a fake that redirects to a
pretend consent screen and answers the callback with a fixed identity.
What's under test is everything around it — the redirect, the user row,
the session cookie, sign-out, the "who am I" and provider-list routes,
and the dependency that guards signed-in-only routes.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from api.auth import providers, session
from api.auth.providers import Identity
from api.v1.endpoints import auth
from src.users import get_user, upsert_from_identity


@pytest.fixture()
def isolated_db(tmp_path):
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    old_database_url = os.environ.pop("DATABASE_URL", None)
    os.environ["DATABASE_PATH"] = str(tmp_path / "auth.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path
        if old_database_url is not None:
            os.environ["DATABASE_URL"] = old_database_url


class FakeProvider:
    def __init__(self, name="google", identity=None, fail=False):
        self.name = name
        self.identity = identity or Identity(
            provider=name, subject="sub-1", email="a@example.com",
            display_name="Ada", avatar_url="https://img.example/a.png",
        )
        self.fail = fail
        self.redirect_uris = []

    async def authorize_redirect(self, request, redirect_uri):
        self.redirect_uris.append(redirect_uri)
        return RedirectResponse(
            f"https://provider.example/consent?redirect_uri={redirect_uri}",
            status_code=302,
        )

    async def fetch_identity(self, request):
        if self.fail:
            raise RuntimeError("consent denied")
        return self.identity


@pytest.fixture()
def fake_provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(providers, "get_provider", lambda name: fake)
    return fake


@pytest.fixture()
def client(isolated_db):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret", same_site="lax")
    app.include_router(auth.router, prefix="/api/auth")

    @app.get("/protected")
    def protected(user: Dict[str, Any] = Depends(session.current_user)):
        return {"hello": user["email"]}

    return TestClient(app)


class TestLoginFlow:
    def test_login_redirects_to_the_provider_with_our_callback(self, client, fake_provider):
        response = client.get("/api/auth/login/google", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"].startswith("https://provider.example/consent")
        assert fake_provider.redirect_uris == ["http://testserver/api/auth/callback/google"]

    def test_public_base_url_builds_the_callback(self, client, fake_provider, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://stocks.example/")
        client.get("/api/auth/login/google", follow_redirects=False)
        assert fake_provider.redirect_uris == ["https://stocks.example/api/auth/callback/google"]

    def test_callback_creates_the_user_signs_in_and_redirects_home(self, client, fake_provider):
        assert client.get("/api/auth/me").json() == {"user": None}
        assert client.get("/protected").status_code == 401

        response = client.get("/api/auth/callback/google?code=x&state=y", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"

        me = client.get("/api/auth/me").json()["user"]
        assert me["email"] == "a@example.com"
        assert me["display_name"] == "Ada"
        assert me["provider"] == "google"
        assert client.get("/protected").json() == {"hello": "a@example.com"}

    def test_signing_in_again_refreshes_the_same_row(self, client, fake_provider):
        client.get("/api/auth/callback/google", follow_redirects=False)
        first = client.get("/api/auth/me").json()["user"]

        fake_provider.identity = Identity(
            provider="google", subject="sub-1", email="new@example.com",
            display_name="Ada L.", avatar_url=None,
        )
        client.get("/api/auth/callback/google", follow_redirects=False)
        second = client.get("/api/auth/me").json()["user"]

        assert second["id"] == first["id"]
        assert second["email"] == "new@example.com"
        assert second["display_name"] == "Ada L."

    def test_logout_ends_the_session(self, client, fake_provider):
        client.get("/api/auth/callback/google", follow_redirects=False)
        assert client.post("/api/auth/logout").json() == {"ok": True}
        assert client.get("/api/auth/me").json() == {"user": None}
        assert client.get("/protected").status_code == 401

    def test_failed_consent_redirects_to_the_failure_page_signed_out(self, client, monkeypatch):
        monkeypatch.setattr(providers, "get_provider", lambda name: FakeProvider(fail=True))
        response = client.get("/api/auth/callback/google", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == auth.LOGIN_FAILED_PATH
        assert client.get("/api/auth/me").json() == {"user": None}

    def test_deleted_account_with_a_live_cookie_is_signed_out(
        self, client, fake_provider, isolated_db
    ):
        from src.storage import UserRecord

        client.get("/api/auth/callback/google", follow_redirects=False)
        with isolated_db.get_session() as db:
            db.query(UserRecord).delete()
            db.commit()
        assert client.get("/api/auth/me").json() == {"user": None}


class TestProviderRegistry:
    def test_unknown_provider_is_404(self, client):
        response = client.get("/api/auth/login/facebook", follow_redirects=False)
        assert response.status_code == 404

    def test_unconfigured_provider_is_503(self, client, monkeypatch):
        for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            monkeypatch.delenv(var, raising=False)
        response = client.get("/api/auth/login/google", follow_redirects=False)
        assert response.status_code == 503

    def test_provider_list_reflects_the_environment(self, client, monkeypatch):
        for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                    "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"):
            monkeypatch.delenv(var, raising=False)
        assert client.get("/api/auth/providers").json() == {"providers": []}
        monkeypatch.setenv("DISCORD_CLIENT_ID", "id")
        monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
        assert client.get("/api/auth/providers").json() == {"providers": ["discord"]}

    def test_real_registry_builds_configured_clients(self, monkeypatch):
        monkeypatch.setenv("DISCORD_CLIENT_ID", "id")
        monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        providers.reset_registry()
        try:
            provider = providers.get_provider("discord")
            assert provider.name == "discord"
        finally:
            providers.reset_registry()


class TestIdentityMapping:
    def test_discord_profile_becomes_an_identity(self):
        import asyncio

        class Client:
            async def get(self, path, token=None):
                class R:
                    def json(self_inner):
                        return {"id": "42", "username": "ada", "global_name": "Ada",
                                "email": "a@example.com", "avatar": "abc"}
                return R()

        identity = asyncio.run(providers._discord_identity(Client(), {}, None))
        assert identity == Identity(
            provider="discord", subject="42", email="a@example.com",
            display_name="Ada", avatar_url="https://cdn.discordapp.com/avatars/42/abc.png",
        )

    def test_google_userinfo_becomes_an_identity(self):
        token = {"userinfo": {"sub": "g1", "email": "g@example.com",
                              "name": "Gee", "picture": "https://p/x"}}
        identity = providers._google_identity(None, token, None)
        assert identity.subject == "g1"
        assert identity.avatar_url == "https://p/x"


class TestUsers:
    def test_upsert_and_get(self, isolated_db):
        user = upsert_from_identity(Identity(provider="google", subject="s", email="e@x"))
        assert get_user(user["id"])["email"] == "e@x"
        assert get_user(999) is None


class TestSessionSettings:
    def test_cookie_https_only_follows_hosting(self, monkeypatch):
        monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        assert session.cookie_is_https_only() is False
        monkeypatch.setenv("PORT", "10000")
        assert session.cookie_is_https_only() is True
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
        assert session.cookie_is_https_only() is False

    def test_missing_session_secret_gets_a_random_one(self, monkeypatch):
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        assert len(session.session_secret()) > 32
        monkeypatch.setenv("SESSION_SECRET", "fixed")
        assert session.session_secret() == "fixed"
