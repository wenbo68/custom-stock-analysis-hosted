# -*- coding: utf-8 -*-
"""Slim FastAPI app for the standalone tiered-analysis service.

Compared with the parent project this serves exactly three things:
- the tiered API under ``/api/v1/tiered``
- a health probe at ``/api/health``
- the built frontend (``web/`` -> ``static/``) as a single-page app

Public-server work (2026-09-14):
- sign-in: Google/Discord OAuth under /api/auth and a signed session
  cookie; CORS is narrowed to CORS_ALLOW_ORIGINS (none by default — the
  frontend is served from the same origin, and the Vite dev server
  proxies /api).
- startup housekeeping: runs execute as in-process threads, so any run
  still "running" when the process starts belongs to a process that
  died — it is marked failed. Old transcript and cache rows are pruned.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from api.auth import session as auth_session
from api.middlewares.error_handler import add_error_handlers
from api.v1.endpoints import auth, settings, tiered

logger = logging.getLogger(__name__)

#: Frontend build output (web/ builds into <repo root>/static).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

#: Root-level files the SPA fallback may serve directly. Everything else
#: gets index.html — user-supplied paths never touch the filesystem.
ROOT_FILE_ALLOWLIST = frozenset({"favicon.ico", "favicon.svg", "vite.svg", "robots.txt"})


def _cors_allow_origins() -> list:
    """Origins allowed to call the API from another site (comma list in
    CORS_ALLOW_ORIGINS). Empty by default: same-origin needs no CORS."""
    raw = os.getenv("CORS_ALLOW_ORIGINS") or ""
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def startup_housekeeping() -> None:
    """Mark orphaned runs failed and prune expired rows. Never fails
    startup: a housekeeping error is logged and the app serves anyway."""
    from src.tiered_analysis import history
    from src.tiered_analysis.cache_store import prune_cache

    try:
        orphaned = history.fail_stale_running_runs()
        if orphaned:
            logger.warning("marked %d orphaned run(s) failed at startup", orphaned)
    except Exception as exc:
        logger.warning("startup run cleanup skipped: %s", exc)
    try:
        history.prune_transcripts()
        prune_cache()
    except Exception as exc:
        logger.warning("startup pruning skipped: %s", exc)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    startup_housekeeping()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Custom Stock Analysis",
        description="Standalone tiered stock analysis (the tiered alt page)",
        version="0.1.0",
        lifespan=_lifespan,
    )

    cors_origins = _cors_allow_origins()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(
        SessionMiddleware,
        secret_key=auth_session.session_secret(),
        session_cookie=auth_session.SESSION_COOKIE,
        max_age=auth_session.SESSION_MAX_AGE_SECONDS,
        same_site="lax",
        https_only=auth_session.cookie_is_https_only(),
    )
    add_error_handlers(app)

    app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
    app.include_router(settings.router, prefix="/api/v1/settings", tags=["Settings"])
    app.include_router(tiered.router, prefix="/api/v1/tiered", tags=["TieredAnalysis"])

    @app.get("/api/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    has_frontend = (STATIC_DIR / "index.html").is_file()
    if has_frontend:
        app.mount(
            "/assets",
            StaticFiles(directory=str(STATIC_DIR / "assets"), check_dir=False),
            name="assets",
        )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"error": "not_found",
                             "message": f"API endpoint /{full_path} not found"},
                )
            if full_path in ROOT_FILE_ALLOWLIST:
                candidate = STATIC_DIR / full_path
                if candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")
    else:
        logger.warning(
            "frontend build not found at %s — API only. "
            "Build it with: cd web && npm install && npm run build",
            STATIC_DIR,
        )

    return app


app = create_app()
