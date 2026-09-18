# -*- coding: utf-8 -*-
"""Offline tests for user settings (hosted-app work, 2026-09-14):
the curated model list, Fernet-encrypted keys that only come back
masked, and the settings API."""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth.providers import Identity
from api.auth.session import current_user
from api.v1.endpoints import settings as settings_api
from src import user_settings
from src.users import upsert_from_identity


@pytest.fixture()
def isolated_db(tmp_path):
    from src.config import Config
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    old_database_url = os.environ.pop("DATABASE_URL", None)
    os.environ["DATABASE_PATH"] = str(tmp_path / "settings.db")
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


@pytest.fixture()
def encryption_key(monkeypatch):
    monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture()
def user(isolated_db, encryption_key):
    return upsert_from_identity(Identity(provider="google", subject="u1", email="u@x"))


class TestCatalog:
    def test_every_model_names_its_provider_and_where_to_get_a_key(self):
        for choice in user_settings.catalog():
            assert choice["id"] and choice["label"]
            assert choice["provider"] in choice["id"].split("/")[0]
            assert choice["key_url"].startswith("https://")

    def test_unknown_model_is_rejected(self):
        with pytest.raises(user_settings.UnknownModel):
            user_settings.model_choice("acme/made-up")

    def test_every_provider_has_a_listed_default_pair(self):
        providers = {choice["provider"] for choice in user_settings.catalog()}
        defaults = user_settings.provider_defaults()
        assert set(defaults) == providers
        for provider, pair in defaults.items():
            assert user_settings.model_choice(pair["main"]).provider == provider
            assert user_settings.model_choice(pair["sub"]).provider == provider
        # the forward-tested pair (daily_stock_analysis fork .env, 2026-09)
        assert defaults["gemini"] == {
            "main": "gemini/gemini-3.8-flash", "sub": "gemini/gemini-3.5-flash-lite",
        }
        assert user_settings.DEFAULT_PROVIDER == "gemini"


class TestEncryption:
    def test_roundtrip_and_mask(self, encryption_key):
        token = user_settings.encrypt_secret("sk-abcdef1234")
        assert token != "sk-abcdef1234"
        assert user_settings.decrypt_secret(token) == "sk-abcdef1234"
        assert user_settings.mask_secret("sk-abcdef1234") == "••••1234"
        assert user_settings.mask_secret("ab") == "••••"
        assert user_settings.mask_secret(None) is None

    def test_missing_or_malformed_key_is_loud(self, monkeypatch):
        monkeypatch.delenv("API_KEY_ENCRYPTION_KEY", raising=False)
        with pytest.raises(user_settings.EncryptionNotConfigured):
            user_settings.encrypt_secret("x")
        monkeypatch.setenv("API_KEY_ENCRYPTION_KEY", "not-a-fernet-key")
        with pytest.raises(user_settings.EncryptionNotConfigured):
            user_settings.encrypt_secret("x")


class TestSaveAndLoad:
    def test_fresh_user_starts_on_the_gemini_pair_and_only_lacks_a_key(self, user):
        view = user_settings.load_user_settings(user["id"])
        assert view["llm_model"] == "gemini/gemini-3.8-flash"
        assert view["llm_sub_model"] == "gemini/gemini-3.5-flash-lite"
        assert view["llm_api_key"] == {"set": False, "hint": None}
        assert set(view["data_keys"]) == {"finnhub", "alphavantage", "fred"}
        bundle = user_settings.run_settings_for(user["id"])
        assert bundle.llm_model == "gemini/gemini-3.8-flash"
        assert bundle.llm_sub_model == "gemini/gemini-3.5-flash-lite"
        assert bundle.is_llm_configured is False
        # a key alone makes the account runnable — on the default pair
        user_settings.save_user_settings(user["id"], llm_api_key="sk-only-1234")
        bundle = user_settings.run_settings_for(user["id"])
        assert bundle.llm_model == "gemini/gemini-3.8-flash"
        assert bundle.is_llm_configured is True

    def test_a_first_save_that_picks_a_model_does_not_drag_the_starting_pair_along(self, user):
        view = user_settings.save_user_settings(user["id"], llm_model="openai/gpt-5.6-sol")
        assert view["llm_model"] == "openai/gpt-5.6-sol"
        assert view["llm_sub_model"] is None

    def test_removed_default_models_stay_removed(self, user):
        # the starting pair is a value like any other: clearing it leaves
        # the field empty (it does not snap back), as on the run form
        view = user_settings.save_user_settings(user["id"], llm_model="")
        assert view["llm_model"] is None
        assert view["llm_sub_model"] == "gemini/gemini-3.5-flash-lite"
        view = user_settings.save_user_settings(user["id"], llm_sub_model="")
        assert view["llm_model"] is None and view["llm_sub_model"] is None
        bundle = user_settings.run_settings_for(user["id"])
        assert bundle.llm_model is None and bundle.llm_sub_model is None
        assert user_settings.load_user_settings(user["id"])["llm_model"] is None

    def test_save_masks_keys_and_the_run_bundle_decrypts_them(self, user):
        view = user_settings.save_user_settings(
            user["id"], llm_model="openai/gpt-5.6-luna", llm_api_key="sk-secret-9876",
            fred_api_key="fred-key-0001",
        )
        assert view["llm_model"] == "openai/gpt-5.6-luna"
        assert view["llm_api_key"] == {"set": True, "hint": "••••9876"}
        assert view["data_keys"]["fred"] == {"set": True, "hint": "••••0001"}
        assert view["data_keys"]["finnhub"] == {"set": False, "hint": None}

        bundle = user_settings.run_settings_for(user["id"])
        assert bundle.llm_model == "openai/gpt-5.6-luna"
        assert bundle.llm_api_key == "sk-secret-9876"
        assert bundle.data_keys == {"fred": "fred-key-0001"}
        assert bundle.is_llm_configured

    def test_omitted_fields_stay_and_empty_string_clears(self, user):
        user_settings.save_user_settings(user["id"], llm_model="openai/gpt-5.6-sol",
                                         llm_api_key="k1", finnhub_api_key="f1")
        view = user_settings.save_user_settings(user["id"], finnhub_api_key="")
        assert view["llm_model"] == "openai/gpt-5.6-sol"
        assert view["llm_api_key"]["set"] is True
        assert view["data_keys"]["finnhub"]["set"] is False

    def test_unknown_model_is_refused(self, user):
        with pytest.raises(user_settings.UnknownModel):
            user_settings.save_user_settings(user["id"], llm_model="acme/x")

    def test_sub_model_rides_into_the_run_and_clears_with_empty_string(self, user):
        view = user_settings.save_user_settings(
            user["id"], llm_model="gemini/gemini-3.1-pro-preview",
            llm_sub_model="gemini/gemini-3.8-flash",
        )
        assert view["llm_sub_model"] == "gemini/gemini-3.8-flash"
        assert user_settings.run_settings_for(user["id"]).llm_sub_model == "gemini/gemini-3.8-flash"
        view = user_settings.save_user_settings(user["id"], llm_sub_model="")
        assert view["llm_sub_model"] is None
        assert view["llm_model"] == "gemini/gemini-3.1-pro-preview"

    def test_sub_model_must_share_the_main_models_provider(self, user):
        user_settings.save_user_settings(user["id"], llm_model="openai/gpt-5.6-sol")
        # one key pays for both, so a sub model from another provider is refused —
        # also when it arrives alone, against the main model already stored
        with pytest.raises(user_settings.ModelMismatch):
            user_settings.save_user_settings(user["id"], llm_sub_model="gemini/gemini-3.8-flash")
        with pytest.raises(user_settings.ModelMismatch):
            user_settings.save_user_settings(
                user["id"], llm_model="deepseek/deepseek-flash", llm_sub_model="openai/gpt-5.6-luna",
            )
        assert user_settings.load_user_settings(user["id"])["llm_sub_model"] is None

    def test_retired_model_reads_back_as_unset(self, user, isolated_db):
        from src.storage import UserSettingsRecord

        user_settings.save_user_settings(
            user["id"], llm_model="openai/gpt-5.6-sol", llm_sub_model="openai/gpt-5.6-luna",
            llm_api_key="sk-secret-9876",
        )
        # a model that was on the list when saved, then dropped off it
        with isolated_db.get_session() as session:
            row = session.get(UserSettingsRecord, user["id"])
            row.llm_model = "openai/gpt-4o"
            row.llm_sub_model = "openai/gpt-4o-mini"
            session.commit()
        view = user_settings.load_user_settings(user["id"])
        assert view["llm_model"] is None
        assert view["llm_sub_model"] is None
        bundle = user_settings.run_settings_for(user["id"])
        assert bundle.llm_model is None
        assert bundle.is_llm_configured is False
        # saving something else must not trip over the stale pair
        user_settings.save_user_settings(user["id"], finnhub_api_key="fh-1234")
        # and a fresh pick from any provider is accepted
        view = user_settings.save_user_settings(user["id"], llm_model="gemini/gemini-3.8-flash")
        assert view["llm_model"] == "gemini/gemini-3.8-flash"

    def test_keys_are_not_stored_in_clear(self, user, isolated_db):
        from src.storage import UserSettingsRecord

        user_settings.save_user_settings(user["id"], llm_api_key="sk-plain-text")
        with isolated_db.get_session() as session:
            row = session.get(UserSettingsRecord, user["id"])
            assert "sk-plain-text" not in (row.llm_api_key_enc or "")


class TestSettingsApi:
    @pytest.fixture()
    def client(self, user):
        app = FastAPI()
        app.include_router(settings_api.router, prefix="/settings")
        app.dependency_overrides[current_user] = lambda: user
        return TestClient(app)

    def test_get_returns_masked_view_plus_catalog_and_provider_defaults(self, client):
        body = client.get("/settings/me").json()
        assert body["llm_model"] == "gemini/gemini-3.8-flash"
        assert body["llm_api_key"]["set"] is False
        assert any(m["id"] == "gemini/gemini-3.8-flash" for m in body["models"])
        assert body["defaults"]["openai"] == {
            "main": "openai/gpt-5.6-terra", "sub": "openai/gpt-5.6-luna",
        }

    def test_put_updates_only_the_given_fields(self, client):
        body = client.put("/settings/me", json={
            "llm_model": "deepseek/deepseek-flash", "llm_api_key": "sk-deep-4321",
        }).json()
        assert body["llm_model"] == "deepseek/deepseek-flash"
        assert body["llm_api_key"] == {"set": True, "hint": "••••4321"}
        body = client.put("/settings/me", json={"alphavantage_api_key": "av-1"}).json()
        assert body["llm_model"] == "deepseek/deepseek-flash"
        assert body["data_keys"]["alphavantage"]["set"] is True
        assert "sk-deep-4321" not in client.get("/settings/me").text

    def test_unknown_model_is_422(self, client):
        response = client.put("/settings/me", json={"llm_model": "acme/x"})
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "unknown_model"

    def test_sub_model_from_another_provider_is_422(self, client):
        response = client.put("/settings/me", json={
            "llm_model": "openai/gpt-5.6-sol", "llm_sub_model": "deepseek/deepseek-flash",
        })
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "model_mismatch"
        body = client.get("/settings/me").json()
        assert body["llm_model"] == "gemini/gemini-3.8-flash"
        assert body["llm_sub_model"] == "gemini/gemini-3.5-flash-lite"

    def test_missing_encryption_key_is_503(self, client, monkeypatch):
        monkeypatch.delenv("API_KEY_ENCRYPTION_KEY")
        response = client.put("/settings/me", json={"llm_api_key": "k"})
        assert response.status_code == 503
        assert response.json()["detail"]["error"] == "encryption_not_configured"

    def test_signed_out_is_401(self, isolated_db):
        from starlette.middleware.sessions import SessionMiddleware

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="t")
        app.include_router(settings_api.router, prefix="/settings")
        assert TestClient(app).get("/settings/me").status_code == 401
