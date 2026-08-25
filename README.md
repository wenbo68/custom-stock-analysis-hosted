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
./start-server.sh                # http://127.0.0.1:8000
```

Frontend development mode (hot reload, proxies /api to :8000):

```bash
cd web && npm run dev
```

## Structured LLM replies

Every AI call that must answer in JSON is protected twice (2026-08-25):
the provider is asked to *enforce* the reply shape while generating
(litellm `response_format` — full schema on models that support it,
plain guaranteed-JSON mode otherwise, silently skipped on models that
support neither), and the reply is *checked* against a pydantic form
with one retry that shows the model what was wrong. The report warns
when a retry was needed. The old fail-soft fallbacks (keep all
articles, no grouping, score order, feed abstracts) remain the last
line of defense.

## LLM transcripts

Every analysis run writes a transcript of its AI exchanges to
`data/llm_transcripts/` — one JSONL file per run, one line per call, with
the pipeline stage, model, full prompt, raw reply, token counts, and the
error when a call failed. When a report shows a warning like "returned no
usable JSON", open the run's transcript to see exactly what the model said.
The file is named in the stored run under `llm_usage.transcript_file`;
files older than 14 days are pruned automatically.

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
