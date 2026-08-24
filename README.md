# Custom Stock Analysis

Standalone tiered stock analysis — the "tiered alt" page extracted from the
[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) fork
into its own app on 2026-08-24.

One page, one job: enter a ticker (A-shares, HK, or US), pick quick or deep
analysis and a max hold time, and get a structured report — technicals,
fundamentals, news, macro, an AI debate, a trade plan with sizing — plus a
run history. Every run also records its buy/sell call as a signal, and the
forward-test script grades those calls against real prices later.

## Layout

- `server.py` / `api/` — FastAPI backend (the tiered API + static frontend)
- `src/tiered_analysis/` — the analysis engine
- `src/storage.py` — sqlite (run history, signals, daily price bars)
- `data_provider/` — multi-source daily price bars with automatic fallback
- `web/` — React frontend (builds into `static/`)
- `scripts/run_forward_test.py` — daily forward-test grid + grading + scoreboard
- `scripts/run_tiered_analysis.py` — one-off CLI run
- `tests/` — offline test suite

## Quick start

```bash
# 1. Backend deps
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 2. Configure (at minimum the LLM model + its provider key)
cp .env.example .env   # then edit

# 3. Frontend
cd web && npm install && npm run build && cd ..

# 4. Run
./.venv/bin/python server.py     # http://127.0.0.1:8000
```

Frontend development mode (hot reload, proxies /api to :8000):

```bash
cd web && npm run dev
```

## Forward test

```bash
./.venv/bin/python scripts/run_forward_test.py                  # today's grid + grade + scoreboard
./.venv/bin/python scripts/run_forward_test.py --summary-only   # no LLM spend
./.venv/bin/python scripts/run_forward_test.py --check          # verify today's cells
```

The script fetches daily bars for every stock with a signal before grading
(`--no-backfill` skips that fetch for offline runs). Edit `WATCHLIST` in the
script to change the daily grid.

## Tests

```bash
./.venv/bin/python -m pytest -m "not network"   # backend (offline)
cd web && npm run lint && npm test              # frontend
```
