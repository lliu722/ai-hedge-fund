# ONBOARDING.md — Read This First

You've just opened the AI Investment System repo. This is a **live** Telegram investment bot running 24/7 on Railway, managing a real multi-asset portfolio. **Do not break it.**

Read this fully before touching anything.

---

## What this system is
A personal investment office that runs as a Telegram bot. It watches markets, researches names, forms buy/sell views, tracks risk, and reviews its own decisions.

Stack: **Python · LangGraph · DeepSeek V4 · Telegram · Notion · Railway.**

---

## Read in this order
1. **This file** — orientation (you are here).
2. **`AGENTS.md`** — the working rules + repo layout. Read it fully.
3. **`src/desks/MASTER.md`** — the architecture: 9 desks (8 idea desks + `pm_risk`). What the system is becoming.
4. **`docs/BUILD_LOG.md`** — what's built, what's next. **Find your work here.**
5. **The desk you're working on** — `src/desks/<desk>/spec/`. Read its spec before touching its code.

---

## The shape of the system (30-second version)
The system is being built as **asset-class desks**. Each desk is a self-contained research+idea unit for one
slice of the market (equity L/S, macro, credit, commodities, options, crypto, event, quant). Desks produce
**`IdeaCard`s** and hand them to **`pm_risk`** — the only desk that sizes positions and manages the book.

There are two codebases living side by side (the **strangler migration**):
- 🟢 **`src/tools/`** — the live bot running today on Railway. Still fully editable.
- 🔵 **`src/desks/`** — the new desk model being built. All new development happens here.

When the desks are proven, we cut over. Until then, both run; neither blocks the other.

---

## The non-negotiable rules (full list in AGENTS.md)
1. **Surgical patches only.** One change at a time.
2. **Commit after every successful change.**
3. **After every change, update `docs/BUILD_LOG.md`** — status line + a Decision Log line, same commit. The 好习惯 this project runs on.
4. **Desks never size.** Only `pm_risk` sets size/weight/allocation.
5. **Never import from `legacy/`.** It's read-only reference — copy what you need into `src/desks/` and rewire.
6. **The bot is live.** Migrate strangler-style — keep it running throughout.
7. **Before large changes, propose a plan and get confirmation.**

The golden rule: **if you change the system, change the docs in the same commit.**

---

## Folder layout
```
.
├── ONBOARDING.md   ← you are here
├── README.md       ← project overview
├── AGENTS.md       ← canonical rules + repo layout (all agents + humans)
├── CLAUDE.md       ← shim: @AGENTS.md + Claude-specific notes
├── src/
│   ├── tools/      🟢 LIVE bot
│   ├── data/       🟢 live-adjacent data
│   └── desks/      🔵 NEW desk model — MASTER.md, DESKS.md, base.py, contracts.py, <desk>/
├── legacy/         ⚪🟠 frozen reference (fork + superseded) — never import
└── docs/
    ├── BUILD_LOG.md  ← status + decision log
    └── archive/      ← old WORK_ORDERs + prior 6-desk-model docs
```

---

## Finding your work
Open `docs/BUILD_LOG.md` → current sprint → take the first unfinished item → read the desk's `spec/` → propose a plan before writing code. The build log is the backlog.

## If something is unclear
1. Check `src/desks/MASTER.md` + `src/desks/DESKS.md` — most architecture questions are answered there.
2. Check the desk's `spec/` — most implementation questions are answered there.
3. Still unclear? Flag it explicitly. Don't make architecture decisions silently — log them.
