# Handoff Document — 2026-06-26

## One Paragraph Summary

A personal investment office running 24/7 as a Telegram bot (`@AI_InvestorL_bot`) on Railway. It tracks 98 names (41 held, 57 watchlist) in a Notion database, sends automated briefings and market alerts, and responds to natural language queries using a DeepSeek V4 LangGraph ReAct agent with 46 registered tools. The system covers the full investment workflow: morning briefing → research → portfolio construction (entry points, sizing, 腾位置) → risk monitoring → automated close alerts with AI shadow portfolio recommendations → monthly 复盘. The only major missing layer is the exit framework (Thesis Watchdog).

---

## Current State

- **46 tools** registered in the LangGraph agent
- **41 held positions**, 57 watchlist names, 98 total in Notion Holdings DB
- Fully operational in production on Railway
- All 65 tests passing
- Last deployment: 2026-06-26 (system prompt overhaul + Entry Points button)

---

## Setup Commands

```bash
git clone https://github.com/lliu722/ai-hedge-fund.git
cd ai-hedge-fund
poetry install
cp .env.example .env   # fill in real keys
poetry run python -m src.tools.telegram_bot
```

---

## Run / Build / Test

```bash
# Run bot
poetry run python -m src.tools.telegram_bot

# Tests
poetry run pytest tests/ -x -q

# Lint + format check
poetry run flake8 src/tools/ --max-line-length=420
poetry run black --check src/tools/

# Deploy
git push origin main   # Railway auto-deploys in ~2 min
```

---

## Key Files

| File | What it is |
|---|---|
| `src/tools/telegram_bot.py` | Entry point — agent, all 46 tools, polling loop |
| `src/tools/scheduler.py` | All automated messages (briefings, alerts, shadow portfolio) |
| `src/tools/notion_holdings.py` | Portfolio read + write-back |
| `src/tools/llm.py` | Shared DeepSeek + Tavily helpers |
| `src/tools/notify.py` | Telegram send (auto-split, inline buttons) |
| `Procfile` | Railway entry point |
| `docs/ARCHITECTURE.md` | Full layer-by-layer system map |
| `docs/NEXT_STEPS.md` | Prioritised backlog |

---

## Known Issues

- `MemorySaver` checkpointer is in-process — conversation context resets on Railway redeploy
- SQLite persistence across redeploys unverified (should work with Railway persistent volume)
- `app/backend`, `app/frontend`, `src/agents/`, `v2/` are legacy/experimental — not in production

---

## Next 5 Tasks (Priority Order)

1. **Thesis Watchdog** — weekly scan of held positions vs saved thesis, fire sell alert when thesis breaks
2. **Macro regime → decisions** — RISK-OFF/STAGFLATION should change shadow portfolio conviction
3. **Recommendation accuracy tracking** — log buy/wait/skip calls, evaluate outcomes after 4 weeks
4. **Macro stress test** — "what if AI falls 30%?" scenario simulation
5. **PDF ingestion** — accept broker research PDFs via Telegram, extract and cross-reference

---

## Risks

- **DeepSeek API unavailability** — no fallback LLM configured. All analysis calls fail if DeepSeek is down.
- **Notion API rate limits** — `get_holdings_cached()` caches on startup. High-traffic periods could hit limits.
- **yfinance breakage** — yfinance is an unofficial API that breaks occasionally. Price data would go stale.
- **Railway cold starts** — `MemorySaver` state is lost; users lose conversation context on every deploy.

---

## What to Read First

1. `AGENTS.md` — directory map, conventions, what not to touch
2. `src/tools/telegram_bot.py` — the full system in one file
3. `docs/ARCHITECTURE.md` — 8-layer investment stack with status per feature
4. `docs/NEXT_STEPS.md` — what to build next
