# -*- coding: utf-8 -*-
"""Entry point: ``python server.py`` or ``uvicorn server:app``."""
from __future__ import annotations

import os

from src.config import get_config  # loads .env before anything else reads it

from api.app import app  # noqa: E402  (uvicorn target)

get_config()

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
