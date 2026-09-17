# Custom Stock Analysis

Standalone tiered stock analysis — the "tiered alt" page extracted from the
[daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) fork
into its own app on 2026-08-24.

One page, one job: enter a ticker (A-shares, HK, or US), pick quick or deep
analysis and a max hold time, and get a structured report — technicals,
fundamentals, news, macro, an AI debate, a trade plan with sizing — plus a
run history.

## Layout

- `server.py` / `api/` — FastAPI backend (the tiered API + static frontend)
- `src/tiered_analysis/` — the analysis engine
- `src/storage.py` — database (run history, transcripts, caches)
- `data_provider/` — multi-source daily price bars with automatic fallback
- `web/` — React frontend (builds into `static/`)
- `scripts/run_tiered_analysis.py` — one-off CLI run
- `tests/` — offline test suite

## Public server

The app can be hosted for many users (public-server branch, 2026-09-14):

- **Sign-in** with Google or Discord (`GOOGLE_*` / `DISCORD_*` client
  credentials, `SESSION_SECRET` for the login cookie). Every run route
  requires a signed-in user.
- **Your own keys.** The user block above New Run holds each user's
  model choice (a curated list) and their LLM key, plus optional
  Finnhub / AlphaVantage / FRED keys that override the server's
  defaults. Keys are encrypted at rest (`APP_ENCRYPTION_KEY`) and only
  ever shown back masked. A run refuses to start until a model and key
  are on file.
- **Private history.** Runs belong to the user who started them; the
  list, detail and transcript routes only show your own.
- **Postgres.** Set `DATABASE_URL` (Neon, Railway, ...) — hosts wipe
  their disk on restart, so nothing durable lives in files: run
  history, transcripts and the fetched-data caches are all tables.
- **Hosting.** The server listens on every interface when the host
  passes `PORT`, and trusts forwarded headers so OAuth callbacks stay
  https. Set `PUBLIC_BASE_URL` to the site's address. A restart marks
  any run still in flight as failed (runs are in-process threads).
- **Run queue.** At most `TIERED_MAX_CONCURRENT_RUNS` analyses (default
  2) run at once across all users; the rest wait in line and start by
  themselves, and a restart resumes whatever was still waiting. Your
  own unfinished run with the same ticker and inputs cannot be started
  twice — the Start popup names the existing one.

See `.env.example` for every variable and where to get each credential.

## Quick start

```bash
# 1. Backend deps
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 2. Configure (sign-in credentials + secrets; see .env.example)
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

Every analysis run stores a transcript of its AI exchanges in the
database — one row per call, with the pipeline stage, model, full prompt,
raw reply, token counts, and the error when a call failed. When a report
shows a warning like "returned no usable JSON", open "View AI transcript"
under the report to see exactly what the model said. Rows older than 14
days are pruned at server startup.

## Fetched-data caches

The macro and world-news fetches and the per-article news
judgments are cached in the database (the `tiered_cache` table), not on
disk, so a host that wipes its disk on restart does not burn the vendors'
daily call budgets. Every row can be refetched; rows untouched for 60
days are pruned at startup.

## Tests

```bash
./.venv/bin/python -m pytest -m "not network"   # backend (offline)
cd web && npm run lint && npm test              # frontend
```
