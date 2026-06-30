# legacy/ — frozen reference code (NOT run)

Nothing in this folder is executed by the live system. Railway runs only
`src/tools/telegram_bot.py` (see root `Procfile`). These are kept as **read-only
reference** — when a new desk reuses logic from here, **copy it into
`src/desks/...` and rewire its imports** rather than importing from `legacy/`.

Internal `from src.xxx` imports inside these files no longer resolve (the modules
moved). That is expected — this code is for reading, not running.

## fork/
The original [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) (MIT) CLI +
web app this project was forked from. Useful reference:
- `fork/agents/` — 20 finished analyst/persona agents (fundamentals, valuation,
  growth, technicals, sentiment + Buffett/Burry/Wood/Lynch/etc.) — the reuse
  source for `equity_ls` deep-dive and idea generation.
- `fork/backtesting/`, `fork/graph/`, `fork/cli/`, `fork/llm/`, `fork/utils/` —
  supporting machinery for the fork's own pipeline.
- `fork/app/` — original web frontend/backend (not used; we run a Telegram bot).
- `fork/v2/` — an experimental backtesting/signals package (never wired in).
- `fork/docker/` — the fork's container (runs `src/main.py`; Railway does not use it).

## superseded/
The first strangler attempt at the new architecture, replaced by `src/desks/`:
- `superseded/core/` — canonical objects (Name, Position, Thesis, Signal, …)
- `superseded/features/` — the prior 6 function-desks (coverage, house_view, quant, risk, morning_briefing)
- `superseded/adapters/` — adapter layer (fundamentals, llm, quant, risk_data)
- `superseded/services/` — evidence service

Kept for reference while `src/desks/` is built and proven. Safe to delete once
the desk model fully covers this ground.
