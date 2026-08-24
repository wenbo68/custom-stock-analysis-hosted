# -*- coding: utf-8 -*-
"""Slim FastAPI app for the standalone tiered-analysis service.

Compared with the parent project this serves exactly three things:
- the tiered API under ``/api/v1/tiered``
- a health probe at ``/api/health``
- the built frontend (``web/`` -> ``static/``) as a single-page app

There is no auth layer: the app is meant to run open on a trusted
machine (owner decision, 2026-08-24).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.middlewares.error_handler import add_error_handlers
from api.v1.endpoints import tiered

logger = logging.getLogger(__name__)

#: Frontend build output (web/ builds into <repo root>/static).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

#: Root-level files the SPA fallback may serve directly. Everything else
#: gets index.html — user-supplied paths never touch the filesystem.
ROOT_FILE_ALLOWLIST = frozenset({"favicon.ico", "favicon.svg", "vite.svg", "robots.txt"})


def create_app() -> FastAPI:
    app = FastAPI(
        title="Custom Stock Analysis",
        description="Standalone tiered stock analysis (the tiered alt page)",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    add_error_handlers(app)

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
