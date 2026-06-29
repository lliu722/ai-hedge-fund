# ONBOARDING.md — Read This First

You've just opened the AI Investment System repo. This is a **live** Telegram investment bot running 24/7 on Railway. It manages a real multi-asset portfolio. **Do not break it.**

This file is your entry point. Read it fully before touching anything.

---

## What this system is

A personal investment office that runs as a Telegram bot. It watches markets, researches names, forms buy/sell views, tracks risk, and reviews its own decisions. It is built as a small team of standing AI "desks" running an investment process — not a single script, not a monolith.

Stack: **Python · LangGraph · DeepSeek V4 · Telegram · Notion · Railway.**

---

## Read in this order

1. **This file** — orientation (you are here).
2. **`AGENTS.md`** — the working rules. Every agent and every human follows these. Read it fully.
3. **`docs/BLUEPRINT.md`** — the architecture. Three parts: the Spine (functions), the Desks (operators), Standards & Support (foundations). This is what the system is.
4. **`docs/BUILD_LOG.md`** — what's built, what's not, and what's in the current sprint. **Find your work here.**
5. **`docs/desks/{desk_name}.md`** — the operations manual for whichever desk you're building or modifying. Read the relevant one before touching that desk's code.

Do not skip steps. The Blueprint and the Build Log are the source of truth. If you skip them and go straight to the code, you will misunderstand the system.

---

## The shape of the system (30-second version)

The architecture has three parts:

- **The Spine** — the investment process as functions: Intelligence → Research → Decision → Monitoring → Review, with Risk cross-cutting all stages. This is *the work.*
- **The Desks** — six standing AI mandates (Research Librarian, Coverage Analyst, Idea Scout, House View, Quant Engine, Risk Watch) that run Spine functions on triggers and push output. This is *who does the work, and when.*
- **Canonical objects** — the shared language every desk and function speaks: `Name · Position · Thesis · Signal · Recommendation · Report · Event`. Nothing communicates in ad-hoc shapes.

Everything in the codebase is one of these three things. If you're unsure where something belongs, the Blueprint has the answer.

---

## The non-negotiable rules (full list in AGENTS.md)

1. **Surgical patches only.** One change at a time.
2. **Commit after every successful change.**
3. **After every change, update `docs/BUILD_LOG.md`** — the status line for that branch AND a new line in the Decision Log. Same commit. This is the 好习惯 this project runs on.
4. **Dependency direction is inward.** Analysis code never imports a data SDK directly (no `import yfinance` in a Spine function). It goes through an adapter interface. The volatile edge depends on the stable core, never the reverse.
5. **Failure is declared, not discovered.** Every adapter has `on_failure`; every desk has `degrade_to`.
6. **The bot is live.** Migrate strangler-style — keep it running throughout.
7. **Before large changes, propose a plan and get confirmation.** Don't start building; start with a plan.

The golden rule: **if you change the system, change the docs in the same commit.** The docs are the source of truth, and you keep them true.

---

## Folder layout

```
.
├── ONBOARDING.md        ← you are here
├── README.md            ← project overview + folder map
├── AGENTS.md            ← canonical agent rules (Codex / Cursor / all non-Claude agents)
├── CLAUDE.md            ← one-line shim: @AGENTS.md  (Claude Code reads this)
└── docs/
    ├── BLUEPRINT.md     ← 图纸 — the architecture (source of truth)
    ├── BUILD_LOG.md     ← 工作日志 — status + current sprint
    └── desks/
        ├── _TEMPLATE.md          ← copy this to spec a new desk
        ├── coverage_analyst.md   ← first deep spec (start here)
        ├── research_librarian.md    (todo)
        ├── idea_scout.md            (todo)
        ├── house_view.md            (todo)
        ├── quant_engine.md          (todo)
        └── risk_watch.md            (todo)
```

---

## Finding your work

Open `docs/BUILD_LOG.md`. Go to **CURRENT SPRINT**. Take the first item that isn't ticked. Read the desk spec if one exists. Then propose a plan before writing code.

If you're a human: the same applies. The build log is the backlog. Work from the top down.

---

## What to do if something is unclear

1. Check `docs/BLUEPRINT.md` first — most architecture questions are answered there.
2. Check the relevant `docs/desks/*.md` — most implementation questions are answered there.
3. If still unclear, flag it explicitly rather than guessing. Add an open question to the relevant desk spec or the build log.

Do not make architecture decisions silently. Log them.
