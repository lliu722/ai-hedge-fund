# AI Investment Management System

A personal investment office running 24/7 as a Telegram bot. Monitors 98 names across a live portfolio, sends automated briefings and alerts, and responds to natural language investment queries.

**Not for redistribution. Personal use.**

---

## What it does

- **Morning briefing (7am HKT)** — portfolio P&L overnight, filtered headlines, read-through analysis, dedicated AI sector update
- **Breaking news alerts** — DeepSeek scores headlines 1–10, only fires at ≥8 relevance
- **Market open alerts** — HK (9:20am HKT) and US (9:20am ET) with pre-market movers, earnings today, macro calendar
- **Market close alerts** — US/HK/EU — positions by move + synthesis + AI Shadow Portfolio (structured verdict: BUY NOW / SET LIMITS / SKIP + per-ticker detail buttons)
- **Deep dives** — 9-section research reports on any ticker, ~45s, auto-injects saved notes and earnings history
- **Proactive analyst** — spots new company names in morning news, auto-runs 4-section mini-dive, max 2/day
- **Theme Radar** — 55-ETF Z-score scanner across all sectors, weekly in Sunday digest
- **Monthly 复盘** — auto-pushed 1st of month, win rate + best/worst + 3 lessons from closed trades
- **Sunday digest** — weekly P&L, sector rotation, theme health, AI stock picks
- **Entry Points** — tiered buy zones (BUY NOW / WAIT / SET LIMIT / SKIP) with live valuation and 52-week high context
- **Portfolio tools** — sizing calculator, 腾位置 (make room), valuation monitor, risk engine

## Tech stack

| Layer | What |
|---|---|
| LLM | DeepSeek V4 (`deepseek-chat`) via LangGraph `create_react_agent` |
| Bot | python-telegram-bot, polling mode, HTML parse mode |
| Hosting | Railway (auto-deploy on git push, ~2 min) |
| Data | yfinance, CoinGecko, FRED API, Tavily web search, SEC EDGAR |
| Storage | Notion (portfolio, trade journal) + SQLite (research library, alerts, earnings history) |
| Language | Python 3.11 |

## File structure

All tools and business logic live in `src/tools/`. See `docs/ARCHITECTURE.md` for the full file map.

```
src/tools/
  telegram_bot.py       — agent + all 46 @tool functions
  scheduler.py          — all scheduled jobs
  notion_holdings.py    — portfolio read + write-back
  llm.py                — shared DeepSeek + Tavily helpers
  recommendations.py    — 4 analyst personas
  deep_dive.py          — 9-section research report
  proactive_analyst.py  — Mode 2: auto mini-dives
  theme_radar.py        — 55-ETF Z-score scanner
  prices.py             — yfinance + CoinGecko cache
  ficc.py               — FRED macro data + regime detector
  risk.py               — concentration, correlation, drawdown
  ... (23 files total)
```

## Setup (local)

```bash
poetry install
cp .env.example .env  # fill in TELEGRAM_BOT_TOKEN, DEEPSEEK_API_KEY, NOTION_API_KEY, TAVILY_API_KEY, FRED_API_KEY
poetry run python -m src.tools.telegram_bot
```

## Test

```bash
poetry run pytest tests/ -x -q   # 65 tests, all should pass
```

## Smoke check

```bash
poetry run python -c "from src.tools.telegram_bot import tools; print(f'OK — {len(tools)} tools loaded')"
```

## Deploy

```bash
git add src/tools/telegram_bot.py [other files]
git commit -m "..."
git push origin main
# Railway auto-deploys in ~2 minutes
```

## Portfolio

98 names tracked in Notion Holdings DB:
- 41 held positions (shares > 0)
- 57 watchlist names (shares = 0, rating tracked)

Current theme focus: AI infrastructure (compute, memory, networking, software & data).

---

*Internal project. See `docs/ARCHITECTURE.md` for full architecture reference.*
