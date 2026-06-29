# AGENTS.md

Canonical agent instructions for this repo. **Source of truth for how to work here.**
(Claude Code reads `CLAUDE.md`, which imports this file. Codex / Cursor / others read this directly.)

## Project
A personal multi-asset investment office that runs 24/7 as a Telegram bot. **It is LIVE — never break it.**
Stack: Python · LangGraph (DeepSeek V4) · Telegram · Notion · Railway. Data: yfinance, FRED, CoinGecko, Tavily, SEC EDGAR, GitHub, arXiv.

## Where the truth lives (read before acting)
- `ONBOARDING.md` — read before anything else.
- `docs/BLUEPRINT.md` — the architecture (Spine = functions, Desks = operators, Standards = foundations).
- `docs/BUILD_LOG.md` — current status of every branch + the active sprint. **Pick work from here.**
- `docs/desks/*.md` — per-desk operations manuals (build a desk straight from its spec).

## Architecture in one paragraph
Work is organised as a **Spine** (Intelligence → Research → Decision → Monitoring → Review, Risk cross-cutting). **Desks** are standing mandates that run Spine functions on triggers and push output. Everything is expressed in **canonical objects** (Name, Position, Thesis, Signal, Recommendation, Report, Event) — never ad-hoc shapes.

## Hard rules (non-negotiable)
1. Surgical patches only; one change at a time.
2. Commit after every successful change.
3. After every change, update `docs/BUILD_LOG.md` (status + file location) and add a Decision Log line.
4. **Dependency direction is inward:** Spine/analysis code never imports a data SDK (e.g. `yfinance`) directly — it goes through an adapter interface. The volatile edge (data, LLM) depends on the stable core, never the reverse.
5. Every adapter declares `on_failure`; every desk declares `degrade_to`. Declared, not discovered.
6. Multi-source desks implement each source as its **own module sharing canonical objects**, and present "A says / B says / C says" then a synthesis. Do **not** run external frameworks as live processes. Vendor logic (Apache-2.0/MIT permitting, with attribution) and translate output into our objects.
7. Appropriate scale: no microservices, no queue; do not migrate to Postgres until SQLite + Notion actually hurt.

## Commands
- Install: `poetry install`
- Run locally: `poetry run python -m src.tools.telegram_bot`
- Deploy: `git push origin main` (Railway auto-deploys in ~2 min)
- Test: `poetry run pytest tests/ -x -q`
- Smoke check: `poetry run python -c "from src.tools.telegram_bot import tools; print(len(tools))"`

## Working order
Follow the CURRENT SPRINT in `docs/BUILD_LOG.md`. Strangler migration — keep the bot running throughout. Before large changes, propose a plan and wait for confirmation.
