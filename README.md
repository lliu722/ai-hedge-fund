# AI Investment System

A personal multi-asset investment office that runs 24/7 as a Telegram bot — it monitors markets, researches names, forms buy/sell views, watches risk, and reviews its own decisions. Built as a small team of standing AI "desks" running an investment process.

## Read order
1. **`docs/BLUEPRINT.md`** (图纸) — the architecture: what the system is and how it fits together.
2. **`docs/BUILD_LOG.md`** (工作日志) — what's built, what's not, and what's in the current sprint.
3. **`docs/desks/`** — one operations manual per desk (start with `coverage_analyst.md`).

## How the AI agents pick this up (cross-tool)
This repo works with Claude Code, Codex, Cursor, and a human, off **one source of truth**:

- **`AGENTS.md`** — canonical agent instructions. Read natively by Codex, Cursor, Copilot, Gemini CLI, etc.
- **`CLAUDE.md`** — a thin shim that imports `AGENTS.md` (Claude Code does not read AGENTS.md natively, so it reads CLAUDE.md, which pulls in AGENTS.md). No duplication, no drift.
- Heavy detail (architecture, desk specs) lives in `docs/` and is loaded on demand — the steering files stay lean on purpose.

> If you ever edit the rules, edit **`AGENTS.md`** only. `CLAUDE.md` just imports it.

## Folder layout
```
.
├── README.md            ← you are here (human front door)
├── AGENTS.md            ← canonical agent rules (Codex/Cursor/…)
├── CLAUDE.md            ← shim: @AGENTS.md  (Claude Code)
├── docs/
│   ├── BLUEPRINT.md     ← 图纸 — architecture (source of truth)
│   ├── BUILD_LOG.md     ← 工作日志 — status + sprint
│   └── desks/
│       ├── _TEMPLATE.md         ← desk spec template
│       ├── coverage_analyst.md  ← ✅ first deep spec
│       ├── research_librarian.md   (todo)
│       ├── idea_scout.md           (todo)
│       ├── house_view.md           (todo)
│       ├── quant_engine.md         (todo)
│       └── risk_watch.md           (todo)
└── src/                 ← code (handlers / features / services / adapters / delivery / core)
```

## Working rules (full list in AGENTS.md)
Surgical patches · commit after each change · update the build log + decision log · dependency direction inward · declared failure policies · never break the live bot.
