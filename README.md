# AI Investment System

A personal multi-asset investment office that runs 24/7 as a Telegram bot — it monitors markets, researches names, forms buy/sell views, watches risk, and reviews its own decisions. Built as a set of standing AI "desks" running an investment process.

## Read order
1. **`ONBOARDING.md`** — orientation. Start here.
2. **`AGENTS.md`** — canonical working rules + repo layout.
3. **`src/desks/MASTER.md`** — the architecture: 9 desks (8 idea desks + `pm_risk`).
4. **`docs/BUILD_LOG.md`** (工作日志) — what's built, what's next, the current sprint.

## How the AI agents pick this up (cross-tool)
This repo works with Claude Code, Codex, Cursor, and a human, off **one source of truth**:
- **`AGENTS.md`** — canonical instructions. Read natively by Codex, Cursor, Copilot, Gemini CLI, etc.
- **`CLAUDE.md`** — a thin shim that imports `AGENTS.md` (Claude Code doesn't read AGENTS.md natively).

> If you ever edit the rules, edit **`AGENTS.md`** only. `CLAUDE.md` just imports it.

## Folder layout
```
.
├── ONBOARDING.md   ← read this first
├── README.md       ← you are here (human front door)
├── AGENTS.md       ← canonical rules + repo layout
├── CLAUDE.md       ← shim: @AGENTS.md (Claude Code)
├── src/
│   ├── tools/      🟢 LIVE bot (Railway runs this)
│   ├── data/       🟢 live-adjacent data
│   └── desks/      🔵 NEW desk model (MASTER.md · DESKS.md · base.py · contracts.py · <desk>/)
├── legacy/         ⚪🟠 frozen reference (fork + superseded) — never import
└── docs/
    ├── BUILD_LOG.md  ← status + decision log
    └── archive/      ← old WORK_ORDERs + prior 6-desk-model docs
```

## Working rules (full list in AGENTS.md)
Surgical patches · commit after each change · update the build log + decision log · desks never size (only `pm_risk` does) · never import from `legacy/` · never break the live bot.
