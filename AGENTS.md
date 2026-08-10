# AGENTS.md

Canonical instructions for this repo. **Source of truth for how to work here.**
(Claude Code reads `CLAUDE.md`, which imports this file. Codex / Cursor / others read this directly.)

## Project
A personal multi-asset investment office that runs 24/7 as a Telegram bot. **It is LIVE — never break it.**
Stack: Python · LangGraph (DeepSeek V4) · Telegram · Notion · Railway.
Data: yfinance, OpenBB, FRED, CoinGecko, Tavily, SEC EDGAR.

## Repo layout (read this before touching anything)
```
src/
  tools/    🟢 LIVE bot — Railway runs `python -m src.tools.telegram_bot`. Never break it.
  data/     🟢 small live-adjacent data layer.
  desks/    🔵 NEW work — the asset-class desk model. All new development goes here.
legacy/
  fork/        ⚪ original ai-hedge-fund (MIT) CLI/web — read-only reference (20 analyst agents live here).
  superseded/  🟠 the prior strangler attempt (core/features/adapters/services) — reference only.
docs/
  BUILD_LOG.md  — status + decision log. Update after every change.
  archive/      — old WORK_ORDERs + the prior 6-desk-model docs.
```
**Rule: never import from `legacy/`.** When reusing legacy logic, COPY it into `src/desks/...` and rewire. See `legacy/README.md`.

## Architecture: the desk model
- Canonical spec: `src/desks/MASTER.md` (map) + `src/desks/DESKS.md` (detail) + each desk's `spec/` folder.
- 8 idea-generating desks emit `IdeaCard`s (`src/desks/contracts.py`); only `pm_risk` sizes/approves.
- Every desk extends the shared contract (`src/desks/base.py`).
- **Strangler migration:** `src/desks/` is built and proven ALONGSIDE the live bot. Do NOT wire it into
  the live entry point or retire `src/tools/` until cutover is explicitly approved.

## Hard rules (non-negotiable)
1. Surgical patches only; one change at a time. Before large changes, propose a plan and wait for confirmation.
2. Commit after every successful change (message names the desk + function touched).
3. After every change, update `docs/BUILD_LOG.md` (status + file) and add a Decision Log line.
4. Desks never set size/weight/allocation — that is `pm_risk` only. A desk that sizes is a contract violation.
5. Vendor, don't run: do not run external frameworks as live processes. Vendor logic (Apache-2.0/MIT
   permitting, **with attribution**) and translate output into our objects.
6. Appropriate scale: no microservices, no queue; do not migrate off SQLite + Notion until they actually hurt.

## Commands
- Install: `poetry install`
- Run live bot: `poetry run python -m src.tools.telegram_bot`
- Deploy: `git push origin main` (Railway auto-deploys in ~2 min)
- Test: `poetry run pytest tests/ -x -q`
- Smoke check (must print 49): `poetry run python -c "from src.tools.telegram_bot import tools; print(len(tools))"`
