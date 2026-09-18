#!/usr/bin/env bash
# Start the web server (backend API + the web app).
#
# Usage:            ./start-server.sh
# Then open:        http://localhost:8000
# Stop it with:     Ctrl+C
#
# The web app is always rebuilt first (a few seconds), so the server
# never serves an out-of-date build. If the build fails, the server
# does not start.

set -euo pipefail
cd "$(dirname "$0")"

echo "Building the web app..."
(cd web && npm run build --silent)

echo "Starting the server..."
.venv/bin/python server.py
