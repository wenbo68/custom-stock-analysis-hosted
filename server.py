# -*- coding: utf-8 -*-
"""Entry point: ``python server.py`` or ``uvicorn server:app``."""
from __future__ import annotations

import os

from src.config import get_config  # loads .env before anything else reads it

from api.app import app  # noqa: E402  (uvicorn target)

get_config()

if __name__ == "__main__":
    import uvicorn

    # Hosting platforms (Render, Railway, ...) hand the port over as PORT
    # and expect the server to listen on every interface; a plain local
    # start keeps the loopback-only default.
    hosted_port = os.getenv("PORT")
    port = int(hosted_port or os.getenv("SERVER_PORT") or "8000")
    host = os.getenv("SERVER_HOST") or ("0.0.0.0" if hosted_port else "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
