# AI Investment Management System

> A personal investment office running 24/7 as a Telegram bot.
> Monitors a live portfolio of 98 names, fires automated briefings and alerts, and answers natural-language investment questions using a DeepSeek V4 AI agent.

**Production bot:** `@AI_InvestorL_bot` · **Hosted on:** Railway · **Not for redistribution**

---

## What This Is

This is a fully automated personal portfolio manager delivered as a Telegram bot. You talk to it like a research analyst — ask about a ticker, request a deep dive, check macro, ask when to buy — and it pulls live data, runs analysis, and gives a structured answer. It also runs on its own: every morning it briefs you, every close it reviews the day, every 2 hours it scans for breaking news.

The AI agent has **46 registered tools** covering research, portfolio management, risk, scheduling, and quant. The portfolio database lives in Notion (98 names: 41 held, 57 watchlist). All analysis is powered by DeepSeek V4 via a LangGraph ReAct agent.

---

## What It Does

### Automated (fires on schedule, no input needed)

| When | What |
|---|---|
| 7am HKT Mon–Fri | Morning briefing: portfolio P&L overnight, filtered headlines, read-through analysis, AI sector update |
| 9:20am HKT | HK market open alert: Hang Seng snapshot, HK positions, Asia news |
| 9:20am ET | US market open alert: pre-market movers, earnings today, macro calendar |
| 4:05pm ET | US market close: positions sorted by move + synthesis |
| 4:05pm HKT | HK market close: same |
| After every close | AI Shadow Portfolio: structured BUY NOW / SET LIMITS / SKIP verdict + per-ticker detail buttons |
| Every 2hrs | Breaking news scan: DeepSeek scores 1–10, only fires if ≥8 |
| 9am HKT Sunday | Weekly digest: P&L, sector rotation, theme health scores, AI stock picks |
| 1st of month | Monthly 复盘: win rate, avg P&L, best/worst, 3 lessons from closed trades |

### On Demand (tap a button or type a question)

| Button / Command | What it does |
|---|---|
| 💼 Portfolio | Live P&L table, all 41 held positions sorted by today's move |
| 📋 Watchlist | All 57 monitored names with ratings |
| 🌅 Briefing | On-demand morning briefing |
| 📅 Earnings | Upcoming earnings dates |
| 🔍 Deep Dive | 9-section research report on any ticker (~45s) |
| 📐 Quant Screen | Factor screen across 98 or ~500 names |
| 🤖 AI Picks | 3 analyst personas each give their top action call |
| 🎓 Explain | Simplify the last response for a junior investor |
| 🎯 Entry Points | Tiered buy zones across watchlist: BUY NOW / WAIT / SET LIMIT / SKIP |

### Natural Language
Ask anything: "What's the macro view?", "Deep dive NVDA", "Should I add to MU?", "What's my biggest risk right now?", "When did I buy TSM and what's my P&L?"

---

## Tech Stack

| Layer | Technology |
|---|---|
| **LLM** | DeepSeek V4 (`deepseek-chat`) — all analysis calls |
| **Agent** | LangGraph `create_react_agent` with `MemorySaver` checkpointer |
| **Bot** | `python-telegram-bot` polling mode, HTML parse mode |
| **Hosting** | Railway — auto-deploy on `git push`, ~2 min |
| **Portfolio DB** | Notion (Holdings DB + Trade Journal) |
| **Local storage** | SQLite — research library, custom alerts, earnings history, paper trades |
| **Prices** | yfinance (equities, ETFs, futures) + CoinGecko (crypto) |
| **News** | Tavily web search (junk-filtered via `llm.py`) |
| **Macro data** | FRED API — yield curve, HY spreads, credit spreads, Fed Funds |
| **Filings** | SEC EDGAR — 10-K, 10-Q, 8-K |
| **Quant** | PyPortfolioOpt (optimizer), scipy, numpy |
| **Language** | Python 3.11 |
| **Package manager** | Poetry (never add requirements.txt) |

---

## Full Folder Structure

### What's Live in Production

```
src/tools/                        ← EVERYTHING THAT RUNS IN PRODUCTION
│
├── telegram_bot.py               ← ENTRY POINT. LangGraph agent + all 46 @tool functions
│                                   + polling loop + keyboard + callback handlers.
│                                   If you're touching the bot, start here.
│
├── scheduler.py                  ← ALL SCHEDULED JOBS.
│                                   Morning briefing, open/close alerts, shadow portfolio,
│                                   breaking news, weekly digest, monthly 复盘.
│                                   _MARKET_CFG dict drives all market alerts (config-driven).
│
├── notion_holdings.py            ← Portfolio source of truth.
│                                   Reads/writes Notion Holdings DB (98 names).
│                                   buy, sell, rate, thesis, add, reload all go through here.
│
├── llm.py                        ← Shared LLM helpers. Use these everywhere.
│                                   call_deepseek(), tavily_search(), clean_news(), fmt_snippet()
│                                   Never inline DeepSeek or Tavily calls elsewhere.
│
├── notify.py                     ← Telegram send layer.
│                                   send_telegram() — auto-splits at 4096 chars.
│                                   send_telegram_with_buttons() — inline keyboard support.
│
├── scheduler.py                  ← All scheduled jobs (briefings, alerts, shadow portfolio)
│
├── recommendations.py            ← 4 analyst personas.
│                                   Cathie Wood, Druckenmiller, Damodaran, Li Wei.
│                                   Parallel execution via ThreadPoolExecutor.
│
├── deep_dive.py                  ← 9-section research report (~45s per ticker).
│                                   Auto-injects saved notes + earnings history.
│
├── proactive_analyst.py          ← Auto mini-dives.
│                                   Extracts new names from morning news, runs 4-section
│                                   dive automatically. Max 2/day, 7-day SQLite cooldown.
│
├── theme_radar.py                ← 55-ETF Z-score scanner across all sectors.
│                                   Detects themes moving outside the portfolio.
│
├── prices.py                     ← Price data layer.
│                                   yfinance + CoinGecko. Thread-safe in-memory cache.
│                                   Handles US, HK (.HK), A-share (.SS/.SZ), crypto.
│
├── ficc.py                       ← Macro data layer.
│                                   FRED API: yield curve, HY spreads, credit spreads, FX.
│                                   get_macro_regime() → RISK-ON / RISK-OFF / STAGFLATION /
│                                   EASING / LATE CYCLE
│
├── risk.py                       ← Risk engine Phase 1.
│                                   Concentration limits, correlation clustering (>0.7),
│                                   drawdown tracking per position + portfolio.
│
├── valuation.py                  ← DCF + comps valuation monitor.
│
├── themes.py                     ← Theme definitions.
│                                   THESIS_MAP (ticker → theme) and THEME_THESIS
│                                   (thesis text, signals, search queries per theme).
│
├── read_through.py               ← Industry read-through map.
│                                   14 trigger tickers → affected portfolio positions.
│                                   e.g. NVDA earnings → TSM, ASML, ALAB
│
├── momentum.py                   ← Developer signal tracker.
│                                   GitHub commit velocity + arXiv paper count per theme.
│
├── catalyst_calendar.py          ← Upcoming catalysts for held + buy-rated names.
│
├── earnings_calendar.py          ← Parallel earnings date fetch. 10 workers.
│
├── news_fetcher.py               ← Tavily news helper for individual tickers + macro.
│
├── sec_filings.py                ← SEC EDGAR fetcher. 10-K, 10-Q, 8-K.
│
├── alert_config.py               ← SQLite: custom price alerts + watchlist price targets.
│                                   Dedup table prevents repeat alerts same day.
│
├── research_library.py           ← SQLite: research notes, deep dives, earnings transcripts.
│                                   Auto-saves every deep dive and earnings call.
│                                   search_research() and save_note() tools.
│
├── api.py                        ← financialdatasets.ai API client.
│                                   Used by legacy src/agents/, not by the bot directly.
│
└── quant/
    ├── factors.py                ← 3-factor model: momentum 12-1m (40%), quality ROE+margin
    │                               (30%), value inv-PE (30%). Z-scored cross-sectionally.
    ├── signals.py                ← Composite score → BUY/WATCH/AVOID (top/bottom 20%).
    ├── optimizer.py              ← Max-Sharpe + DiscreteAllocation (PyPortfolioOpt).
    │                               Ledoit-Wolf covariance shrinkage.
    ├── backtest.py               ← Walk-forward 12-1 momentum backtest. No external libs.
    ├── paper_trade.py            ← SQLite paper portfolio with real-time P&L.
    └── universe.py               ← 98 Notion names or S&P 500 (~500) from Wikipedia.
```

### Legacy Code (not in production, do not touch casually)

```
src/agents/                       ← Multi-agent framework (pre-bot era).
│                                   14 investor persona agents (Warren Buffett, Peter Lynch,
│                                   Michael Burry, etc.) + risk manager + portfolio manager.
│                                   Used by src/main.py CLI. NOT called by the Telegram bot.
│
src/backtesting/                  ← CLI backtesting engine for legacy agents.
src/graph/                        ← LangGraph graph for legacy multi-agent flow.
src/llm/                          ← LLM factory for legacy agents.
src/data/                         ← Pydantic models + cache for financialdatasets.ai API.
src/cli/                          ← CLI input utilities for legacy main.py.
src/main.py                       ← Legacy entry point (not Railway entry point).

v2/                               ← Experimental V2 pipeline. Not in production.
│                                   Event study engine, PEAD signals, quant pipeline.
│                                   Interesting research but maintenance status unknown.

app/backend/                      ← FastAPI backend. Not deployed.
│                                   SQLAlchemy + Alembic, flow management, API key handling.
│                                   Could be activated but not connected to the bot.

app/frontend/                     ← React + Vite + Tailwind frontend. Not deployed.
│                                   Was built to visualise the legacy multi-agent output.
```

### Config and Infra

```
Procfile                          ← Railway entry point: worker: python -m src.tools.telegram_bot
pyproject.toml                    ← All dependencies. Poetry only — never add requirements.txt
poetry.lock                       ← Lock file. Commit this on every dependency change.
.env                              ← Real secrets. Never committed.
.env.example                      ← Template. Commit changes here, not to .env.
.gitignore                        ← Excludes .env, *.db, __pycache__, node_modules, etc.
docker/                           ← Docker setup for local dev. Railway does NOT use this.
```

### Docs

```
AGENTS.md                         ← Full developer guide for humans and AI agents.
CLAUDE.md                         ← Claude-specific workflow + post-push checklist.
docs/ARCHITECTURE.md              ← 8-layer investment stack, full tool list, V3 status.
docs/NEXT_STEPS.md                ← Prioritised backlog with acceptance criteria.
docs/DECISIONS.md                 ← Why key technical decisions were made.
docs/RUNBOOK.md                   ← Debugging, setup, manual test commands.
docs/PROJECT_STATE.md             ← What works, what's partial, what's unknown.
docs/HANDOFF.md                   ← Concise current-state handoff.
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
# Required — the bot won't start without these
TELEGRAM_BOT_TOKEN=         # From @BotFather
TELEGRAM_CHAT_ID=           # Your personal chat ID
DEEPSEEK_API_KEY=           # deepseek.com
NOTION_API_KEY=             # Notion integration token
TAVILY_API_KEY=             # tavily.com (news search)
FRED_API_KEY=               # fred.stlouisfed.org (macro data)

# Optional
COINGECKO_API_KEY=          # Free tier works without this

# Legacy agents only (not needed for the Telegram bot)
FINANCIAL_DATASETS_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

Notion database IDs are hardcoded in `notion_holdings.py` — do not change unless recreating the Notion DB.

---

## How to Run Locally

```bash
# 1. Clone and install
git clone https://github.com/lliu722/ai-hedge-fund.git
cd ai-hedge-fund
poetry install

# 2. Set up environment
cp .env.example .env
# Edit .env with real keys

# 3. Smoke check — should print "OK — 46 tools loaded"
poetry run python -c "from src.tools.telegram_bot import tools; print(f'OK — {len(tools)} tools loaded')"

# 4. Run the bot
poetry run python -m src.tools.telegram_bot
```

The bot starts polling immediately. Open Telegram and message `@AI_InvestorL_bot`.

---

## Tests

```bash
poetry run pytest tests/ -x -q
# Expected: 65 passed
```

Tests cover the legacy API client, cache, and CLI. The bot tools and scheduler are not covered by automated tests — use the manual test commands in `docs/RUNBOOK.md`.

---

## How to Deploy

Railway auto-deploys on every push to `main`. No manual step needed.

```bash
git add <files>
git commit -m "description"
git push origin main
# Wait ~2 minutes, then test in Telegram
```

If something breaks, check Railway dashboard logs. Most failures are: syntax error in `telegram_bot.py`, or a new import that doesn't exist in the Railway environment.

---

## What's Fully Built and Working

See `docs/PROJECT_STATE.md` for the full matrix. Short version:

✅ Morning briefing, Sunday digest, breaking news alerts  
✅ Market open + close alerts (US, HK, EU)  
✅ AI Shadow Portfolio post-close (verdict + per-ticker drill-down buttons)  
✅ Entry Points analysis (tiered buy zones with live valuation)  
✅ Deep dive (9-section, any ticker)  
✅ Proactive analyst (auto mini-dives from morning news)  
✅ Portfolio P&L, watchlist, earnings calendar  
✅ Notion write-back (buy, sell, rate, thesis, add, reload)  
✅ Trade journal (auto-log on buy, auto-close with P&L on sell)  
✅ Risk engine (concentration, correlation, drawdown)  
✅ Macro regime detector (FRED → RISK-ON / RISK-OFF / STAGFLATION / EASING / LATE CYCLE)  
✅ Theme health scores, theme radar (55-ETF Z-score)  
✅ Quant system (factor screen, optimizer, backtest, paper trading)  
✅ Monthly 复盘, custom price alerts, watchlist price targets  
✅ Research library (SQLite — auto-saves deep dives + earnings, searchable)  

---

## What's In Progress / Partially Built

⚠️ **Macro regime → decisions** — regime is detected but doesn't change shadow portfolio or entry point recommendations yet  
⚠️ **Legacy code** — `src/agents/`, `app/backend/`, `v2/` exist but are not wired to the production bot

---

## What's Next (Priority Order)

1. **Thesis Watchdog** — weekly scan of held positions vs saved thesis, fire sell alert when thesis breaks. This is the missing exit framework.
2. **Macro regime → decisions** — RISK-OFF should make shadow portfolio more cautious; STAGFLATION should flag growth names.
3. **Recommendation accuracy tracking** — log buy/wait/skip calls, evaluate outcomes after 4 weeks.
4. **Macro stress test** — "what if AI falls 30%?" portfolio impact simulation.
5. **PDF ingestion** — accept broker research PDFs via Telegram.

Full specs with acceptance criteria: `docs/NEXT_STEPS.md`

---

## Working Rules for This Repo

1. **Surgical edits** — small targeted changes, not full file rewrites
2. **All bot tools go in `telegram_bot.py`** — `bot_tools.py` was deleted, do not recreate it
3. **Poetry only** — never create `requirements.txt`; use `poetry add <package>`
4. **Shared LLM calls via `llm.py`** — never inline `requests.post` to DeepSeek or Tavily directly
5. **HTML parse mode only** — all Telegram messages use `<b>`, `<i>` tags; no Markdown
6. **Bullets are `•` not `-`** in all bot output
7. **After every push**: update Notion Architecture & Decision Log, update `CLAUDE.md` tool count, update `memory/project_state.md` (see `CLAUDE.md` for the full checklist)
8. **Test before pushing**: run the smoke check — `poetry run python -c "from src.tools.telegram_bot import tools; print(len(tools))"`
9. **Don't touch**: `Procfile`, `pyproject.toml` Python version, Notion DB field names, scheduler timezone logic

---

## Handover Protocol

### Coming In Cold (Human or AI Agent)

**2-minute orientation:**
1. Read this README top to bottom
2. Read `AGENTS.md` — directory map, conventions, what not to touch
3. Check `docs/PROJECT_STATE.md` — current state, known issues
4. Check `docs/NEXT_STEPS.md` — what to build next and why
5. Run smoke check: `poetry run python -c "from src.tools.telegram_bot import tools; print(f'OK — {len(tools)} tools loaded')"`

**Starting a dev session:**
- Always `git pull` first
- Check `CLAUDE.md` for current tool count and state
- Understand what's live before changing anything
- For the bot: your edit surface is almost always `src/tools/telegram_bot.py` and/or `src/tools/scheduler.py`

### Handing Off Cleanly (End of Session)

Before closing any session where code was changed:

1. **Push all changes** — `git push origin main`
2. **Update Notion** — append to Architecture & Decision Log (`38770984-77e4-8125-a509-fe1325e133fd`): what was built, decisions made, tool count
3. **Update `CLAUDE.md`** — bump tool count if it changed, update current state date
4. **Update memory** — `memory/project_state.md` and `memory/feedback_rules.md` if anything new was learned
5. **Commit the doc updates** — `git push origin main` again

The next person (or next session) should be able to open this README and be fully oriented with zero prior context.

---

## Notion IDs (for reference)

| Resource | ID |
|---|---|
| Architecture & Decision Log | `38770984-77e4-8125-a509-fe1325e133fd` |
| Master Plan | `38870984-77e4-81bb-9eab-e4739d14ca4c` |
| Master Roadmap | `38b7098477e4812e887cf7e38af7c824` |
| Holdings DB | `9dd63515-c7ae-4f2c-bbc9-a73c6c65bbd1` |
| Trade Journal DB | `57ec5347-fc06-490d-9a60-e99e65a3d9bc` |
| Master page | `38870984-77e4-818f-bd8b-ff154aa37a35` |

---

*Last updated: 2026-06-26 — 46 tools — 41 held positions — 57 watchlist*
