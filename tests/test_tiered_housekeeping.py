# -*- coding: utf-8 -*-
"""Offline tests for the public-server storage work (2026-09-14):

- DATABASE_URL (hosted Postgres) beats the sqlite path, with the driver
  spelled out the way SQLAlchemy needs it;
- startup housekeeping marks orphaned "running" runs failed and prunes
  old transcript and cache rows;
- the per-run transcript round-trips through the database and is served
  by its own endpoint;
- the database-backed cache store round-trips, tolerates corrupt rows,
  and never raises.
"""
from __future__ import annotations

import os
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints import tiered
from src.config import Config, _normalize_database_url
from src.tiered_analysis import history
from src.tiered_analysis.cache_store import DbCacheStore, prune_cache
from src.tiered_analysis.llm_support import LlmTranscript


@pytest.fixture()
def isolated_db(tmp_path):
    from src.storage import DatabaseManager

    old_database_path = os.environ.get("DATABASE_PATH")
    old_database_url = os.environ.pop("DATABASE_URL", None)
    os.environ["DATABASE_PATH"] = str(tmp_path / "housekeeping.db")
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


class TestDatabaseUrl:
    def test_postgres_urls_get_the_driver_spelled_out(self):
        assert _normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
        assert (
            _normalize_database_url("postgresql://u:p@h/db?sslmode=require")
            == "postgresql+psycopg://u:p@h/db?sslmode=require"
        )
        assert _normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"

    def test_database_url_wins_over_the_sqlite_path(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
        monkeypatch.setenv("DATABASE_PATH", "/nowhere/x.db")
        Config.reset_instance()
        try:
            assert Config().get_db_url() == "postgresql+psycopg://u:p@h/db"
        finally:
            Config.reset_instance()

    def test_without_database_url_the_sqlite_path_is_used(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "x.db"))
        Config.reset_instance()
        try:
            assert Config().get_db_url().startswith("sqlite:///")
        finally:
            Config.reset_instance()


class TestStartupHousekeeping:
    def test_running_runs_are_marked_failed(self, isolated_db):
        history.create_run("orphan", "AAPL")
        history.create_run("finished", "MSFT")
        history.mark_done("finished", {"symbol": "MSFT"})

        assert history.fail_stale_running_runs() == 1

        orphan = history.get_run("orphan")
        assert orphan["status"] == "failed"
        assert orphan["error"] == history.STALE_RUN_ERROR
        assert history.get_run("finished")["status"] == "done"
        assert history.fail_stale_running_runs() == 0

    def test_old_transcript_rows_are_pruned_fresh_ones_kept(self, isolated_db):
        from src.storage import TieredRunTranscriptRecord, utc_naive_now

        old = utc_naive_now() - timedelta(days=history.TRANSCRIPT_MAX_AGE_DAYS + 1)
        with isolated_db.get_session() as session:
            session.add(TieredRunTranscriptRecord(
                task_id="old", seq=1, created_at=old, stage="s", model="m",
            ))
            session.add(TieredRunTranscriptRecord(
                task_id="fresh", seq=1, stage="s", model="m",
            ))
            session.commit()

        assert history.prune_transcripts() == 1
        assert history.list_transcript("old") == []
        assert len(history.list_transcript("fresh")) == 1

    def test_app_startup_runs_the_housekeeping(self, isolated_db):
        from api.app import create_app

        history.create_run("orphan", "AAPL")
        with TestClient(create_app()) as client:
            assert client.get("/api/health").status_code == 200
        assert history.get_run("orphan")["status"] == "failed"

    def test_app_startup_resumes_queued_runs(self, isolated_db, monkeypatch):
        """A run left ``queued`` by the previous process starts again
        under the new one (the line lives in the database)."""
        import time
        from unittest.mock import patch

        from cryptography.fernet import Fernet

        from api.app import create_app
        from api.auth.providers import Identity
        from src.user_settings import save_user_settings
        from src.users import upsert_from_identity

        monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        owner = upsert_from_identity(Identity(provider="google", subject="q"))
        save_user_settings(owner["id"], llm_model="gemini/gemini-3.8-flash",
                           llm_api_key="k")
        history.create_run("waiting", "AAPL", owner_id=owner["id"],
                           status=history.STATUS_QUEUED,
                           inputs={"tier": 2, "hold_weeks": 1})
        seen = {}

        def fake_run(code, **kwargs):
            seen.update(kwargs, code=code)
            from tests.test_tiered_api import _outcome
            return _outcome(code)

        with patch.object(tiered, "_run_analysis", fake_run):
            with TestClient(create_app()) as client:
                assert client.get("/api/health").status_code == 200
                deadline = time.time() + 5
                while time.time() < deadline and history.get_run("waiting")["status"] != "done":
                    time.sleep(0.05)
        assert history.get_run("waiting")["status"] == "done"
        assert seen["code"] == "AAPL"
        assert seen["depth"] == 2
        assert seen["hold_weeks"] == 1


class TestTranscriptStorage:
    def test_for_run_writes_rows_readable_in_call_order(self, isolated_db):
        transcript = LlmTranscript.for_run("task-9")
        transcript.record(
            stage="tier1_analysis", model="gemini/x", temperature=0.0,
            prompt="first", reply="one", prompt_tokens=3, completion_tokens=1,
            duration_ms=10, structured="schema",
        )
        transcript.record(
            stage="trade_plan", model="gemini/x", temperature=0.0,
            prompt="second", reply=None, error="RuntimeError('boom')",
        )

        rows = history.list_transcript("task-9")
        assert [r["seq"] for r in rows] == [1, 2]
        assert rows[0]["stage"] == "tier1_analysis"
        assert rows[0]["prompt"] == "first"
        assert rows[0]["reply"] == "one"
        assert rows[0]["structured"] == "schema"
        assert rows[1]["reply"] is None
        assert "boom" in rows[1]["error"]
        assert history.list_transcript("unknown") == []

    def test_transcript_endpoint_serves_the_rows_and_404s_unknown_runs(self, isolated_db):
        from api.auth.session import current_user

        app = FastAPI()
        app.include_router(tiered.router, prefix="/tiered")
        app.dependency_overrides[current_user] = lambda: {"id": 7}
        client = TestClient(app)

        history.create_run("task-9", "AAPL", owner_id=7)
        LlmTranscript.for_run("task-9").record(
            stage="s", model="m", temperature=0.0, prompt="p", reply="r",
        )

        response = client.get("/tiered/runs/task-9/transcript")
        assert response.status_code == 200
        [item] = response.json()["items"]
        assert item["prompt"] == "p"
        assert item["reply"] == "r"
        assert client.get("/tiered/runs/nope/transcript").status_code == 404


class TestDbCacheStore:
    def test_roundtrip_overwrite_and_missing(self, isolated_db):
        store = DbCacheStore()
        assert store.read("k") is None
        store.write("k", {"a": [1, 2]})
        assert store.read("k") == {"a": [1, 2]}
        store.write("k", [3])
        assert store.read("k") == [3]

    def test_corrupt_row_reads_as_missing(self, isolated_db):
        from src.storage import TieredCacheRecord

        with isolated_db.get_session() as session:
            session.add(TieredCacheRecord(key="bad", value_json="{not json"))
            session.commit()
        assert DbCacheStore().read("bad") is None

    def test_old_rows_are_pruned_fresh_ones_kept(self, isolated_db):
        from src.storage import TieredCacheRecord, utc_naive_now

        with isolated_db.get_session() as session:
            session.add(TieredCacheRecord(
                key="old", value_json="1",
                updated_at=utc_naive_now() - timedelta(days=61),
            ))
            session.add(TieredCacheRecord(key="fresh", value_json="2"))
            session.commit()
        assert prune_cache() == 1
        assert DbCacheStore().read("old") is None
        assert DbCacheStore().read("fresh") == 2

    def test_database_trouble_never_raises(self, monkeypatch):
        from src.storage import DatabaseManager

        def explode():
            raise RuntimeError("no database")

        monkeypatch.setattr(DatabaseManager, "get_instance", staticmethod(explode))
        store = DbCacheStore()
        assert store.read("k") is None
        store.write("k", 1)  # logged, not raised


class TestRenameMigration:
    """The 2026-09-17 rename of dimension and stage identifiers rewrites
    runs stored under the old names once, at startup."""

    OLD_RESULT = (
        '{"dimensions": [{"dimension": "macro_econ", "payload": {}},'
        ' {"dimension": "company_events"}, {"dimension": "world_events"}],'
        ' "summary": {"macro_econ": [], "company_events": [], "world_events": []},'
        ' "evidence": ["macro_econ.cpi", "company_events.news_coverage.items.3.text"],'
        ' "narrative": "macro_econ_us is not a stored name",'
        ' "llm_usage": {"stages": {"tier1_quick": {"calls": 1}, "tier2_debate": {},'
        ' "plan_adjust": {}, "unattributed": {}}}}'
    )

    def test_rewrites_names_keys_refs_and_stages_but_not_prose(self):
        from src.storage import rename_stored_identifiers

        renamed = rename_stored_identifiers(self.OLD_RESULT)
        for old in ("macro_econ\"", "company_events", "world_events",
                    "tier1_quick", "tier2_debate", "plan_adjust", "unattributed"):
            assert old not in renamed
        assert '"dimension": "macro_economy"' in renamed
        assert '"company_news": []' in renamed
        assert '"macro_economy.cpi"' in renamed
        assert '"company_news.news_coverage.items.3.text"' in renamed
        assert '"tier1_analysis": {"calls": 1}' in renamed
        assert '"trade_plan": {}' in renamed
        assert '"unknown": {}' in renamed
        # Prose is left alone, and a second pass changes nothing.
        assert "macro_econ_us is not a stored name" in renamed
        assert rename_stored_identifiers(renamed) == renamed

    def test_startup_rewrites_old_rows_once(self, isolated_db):
        from src.storage import (
            DatabaseManager, DatabaseSchemaMigration, RENAME_MIGRATION_VERSION,
            TieredRunRecord, TieredRunTranscriptRecord,
        )

        with isolated_db.get_session() as session:
            # A fresh database already carries the marker; pretend it is
            # a database from before the rename.
            session.query(DatabaseSchemaMigration).filter_by(
                version=RENAME_MIGRATION_VERSION
            ).delete()
            session.add(TieredRunRecord(
                task_id="old-run", stock_code="AAPL", status="done",
                result_json=self.OLD_RESULT,
            ))
            session.add(TieredRunRecord(
                task_id="running", stock_code="AAPL", status="running", result_json=None,
            ))
            session.add(TieredRunTranscriptRecord(
                task_id="old-run", seq=1, stage="plan_adjust", prompt="p",
            ))
            session.add(TieredRunTranscriptRecord(
                task_id="old-run", seq=2, stage="company_events", prompt="p",
            ))
            session.commit()

        DatabaseManager.reset_instance()
        db = DatabaseManager.get_instance()

        with db.get_session() as session:
            run = session.query(TieredRunRecord).filter_by(task_id="old-run").one()
            assert '"macro_economy"' in run.result_json
            assert "macro_econ\"" not in run.result_json
            stages = [
                r.stage for r in session.query(TieredRunTranscriptRecord)
                .filter_by(task_id="old-run").order_by(TieredRunTranscriptRecord.seq)
            ]
            # News-screen calls are staged under their dimension's name.
            assert stages == ["trade_plan", "company_news"]
            assert session.get(DatabaseSchemaMigration, RENAME_MIGRATION_VERSION) is not None
