# AGENTS.md — Developer & Agent Guide

The canonical reference for any developer or coding agent working on this repo.
Read this before touching anything. CLAUDE.md adds Claude-specific notes on top.

---

## What This Project Is

A personal investment office running 24/7 as a Telegram bot (`@AI_InvestorL_bot`) on Railway.
It monitors 98 names (41 held, 57 watchlist), sends automated briefings and alerts, and responds
to natural language investment queries using DeepSeek V4 via a LangGraph ReAct agent.

**This is a live system managing a real portfolio. Every push auto-deploys in ~2 minutes.**

---

## Directory Structure

```
src/tools/              ← ALL active business logic lives here
  telegram_bot.py       ← Entry point: LangGraph agent + all 46 @tool functions + polling loop
  scheduler.py          ← All scheduled jobs (briefings, alerts, open/close, shadow portfolio)
  notion_holdings.py    ← Notion Holdings DB read/write (98 names, paginated)
  llm.py                ← Shared helpers: call_deepseek(), tavily_search(), clean_news(), fmt_snippet()
  recommendations.py    ← 4 analyst personas (Cathie Wood, Druckenmiller, Damodaran, Li Wei)
  deep_dive.py          ← 9-section research report (~45s)
  proactive_analyst.py  ← Auto mini-dives on new names spotted in morning news
  theme_radar.py        ← 55-ETF Z-score scanner across all sectors
  prices.py             ← yfinance + CoinGecko, thread-safe cache, HK/A-share/crypto support
  ficc.py               ← FRED API: yield curve, credit spreads, FX, macro regime detector
  risk.py               ← Concentration, correlation, drawdown (Phase 1)
  valuation.py          ← DCF + comps valuation monitor
  alert_config.py       ← SQLite: custom price alerts + watchlist targets
  research_library.py   ← SQLite: deep dives, earnings, manual notes
  themes.py             ← THESIS_MAP (ticker→theme) + THEME_THESIS (per-theme thesis/signals)
  read_through.py       ← Industry read-through map (14 trigger tickers → affected positions)
  momentum.py           ← GitHub commit velocity + arXiv paper count per theme
  catalyst_calendar.py  ← Upcoming catalysts for held + buy-rated names
  earnings_calendar.py  ← Parallel earnings date fetch (10 workers)
  news_fetcher.py       ← Tavily news helper for tickers and macro queries
  sec_filings.py        ← SEC EDGAR: 10-K, 10-Q, 8-K fetcher
  notify.py             ← Telegram sender (auto-split at 4096 chars, inline buttons)
  api.py                ← financialdatasets.ai API client (used by legacy src/ agents)
  quant/
    factors.py          ← 3-factor model: momentum (40%), quality (30%), value (30%)
    signals.py          ← Composite score → BUY/WATCH/AVOID
    optimizer.py        ← Max-Sharpe + DiscreteAllocation (PyPortfolioOpt)
    backtest.py         ← Walk-forward 12-1 momentum backtest
    paper_trade.py      ← SQLite paper portfolio
    universe.py         ← 98 Notion names or S&P 500 (~500) from Wikipedia

src/agents/             ← Legacy multi-agent framework (not used by the bot)
src/data/               ← Cache + Pydantic models for legacy agents
src/graph/              ← LangGraph graph definitions (legacy)
src/llm/                ← LLM factory for legacy agents
src/backtesting/        ← CLI backtester (legacy)

app/backend/            ← FastAPI backend (legacy, not deployed)
app/frontend/           ← React/Vite frontend (legacy, not deployed)
v2/                     ← Experimental V2 pipeline (not in production)
docker/                 ← Docker setup (Railway uses Procfile, not Docker)
tests/                  ← pytest suite (65 tests, all passing)
docs/                   ← Architecture, roadmap, runbook
```

**Only `src/tools/` is active in production.** Everything else is legacy or experimental.

---

## What to Read First

1. `src/tools/telegram_bot.py` — the whole system starts and ends here
2. `src/tools/scheduler.py` — all automated messages
3. `src/tools/llm.py` — shared helpers used everywhere
4. `src/tools/notion_holdings.py` — how portfolio data is read
5. `docs/ARCHITECTURE.md` — full layer-by-layer system map

---

## Important Commands

```bash
# Install dependencies
poetry install

# Run the bot locally (requires .env with all keys)
poetry run python -m src.tools.telegram_bot

# Run tests
poetry run pytest tests/ -x -q

# Lint
poetry run flake8 src/tools/ --max-line-length=420

# Format check
poetry run black --check src/tools/

# Deploy (Railway auto-deploys on push, ~2 min)
git push origin main
```

---

## Adding a New Tool

1. Write a `@tool` function in `src/tools/telegram_bot.py`
2. Add it to the `tools = [...]` list in the same file
3. If it needs a keyboard button, add to `build_keyboard()` and `handle_callback()`
4. Commit and push — Railway deploys automatically

---

## Coding Conventions

- **No `requirements.txt`** — Poetry only. Never add one.
- **Surgical edits** — prefer small targeted changes over full file rewrites
- **All tools in `telegram_bot.py`** — `bot_tools.py` was deleted; do not recreate it
- **Shared LLM calls via `llm.py`** — never inline `requests.post` to DeepSeek or Tavily
- **HTML parse mode** — all Telegram messages use HTML tags (`<b>`, `<i>`), never markdown
- **Bullets** — use `•` not `-` in all bot output
- **No `---` dividers** — use `—` (em-dash) in messages
- **Thread safety** — `prices.py` uses a lock; scheduler uses `ThreadPoolExecutor`

---

## Do Not Casually Change

| File / Area | Why |
|---|---|
| `src/tools/notion_holdings.py` — DB field names | Notion schema changes break all reads |
| `src/tools/scheduler.py` — cron timing | Times are HKT/ET — wrong timezone = missed alerts |
| `src/tools/telegram_bot.py` — `tools = [...]` list | Missing entry = agent can't call the tool |
| `Procfile` | Railway entry point — changing it kills the deployment |
| `pyproject.toml` — python version | Pinned to 3.11 for Railway compatibility |
| `.env` variable names | Any rename breaks environment reads across all files |

---

## Environment Variables Required

See `.env.example` for the full list. Key ones:

| Variable | Used by |
|---|---|
| `TELEGRAM_BOT_TOKEN` | All Telegram sends |
| `TELEGRAM_CHAT_ID` | All Telegram sends |
| `DEEPSEEK_API_KEY` | Every LLM call |
| `NOTION_API_KEY` | Holdings DB read/write |
| `TAVILY_API_KEY` | News search |
| `FRED_API_KEY` | Macro data |
| `COINGECKO_API_KEY` | Crypto prices (optional) |

---

## Testing

```bash
poetry run pytest tests/ -x -q
```

65 tests, all passing. Tests cover:
- API rate limiting (`tests/test_api_rate_limiting.py`)
- Ticker alias resolution (`tests/test_cli_ticker_alias.py`)
- Price cache (`tests/test_cache.py`)
- Backtesting suite (`tests/backtesting/`)

Tests do **not** cover the bot tools or scheduler — those require live API keys.

---

## Deployment

- **Platform:** Railway
- **Entry point:** `Procfile` → `worker: python -m src.tools.telegram_bot`
- **Trigger:** every `git push origin main` auto-deploys in ~2 minutes
- **No Docker** — Railway uses the Procfile directly
- **No build step** — Poetry installs on Railway's build phase

---

## Current Priorities

See `docs/NEXT_STEPS.md` for the prioritised backlog. Top items:
1. Thesis Watchdog — proactive sell signal when thesis breaks
2. Macro regime wired into decisions (currently detected but ignored)
3. Recommendation accuracy tracking
