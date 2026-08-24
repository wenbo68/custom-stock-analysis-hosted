#!/usr/bin/env bash
# Start the web server (backend API + the built web app in static/).
#
# Usage:            ./start-server.sh
# Then open:        http://localhost:8000
# Stop it with:     Ctrl+C
#
# Note: if you changed frontend code, rebuild it first so the server
# serves the new version:  cd web && npm run build

cd "$(dirname "$0")"
.venv/bin/python server.py
