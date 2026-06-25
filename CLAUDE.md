# ⚠️ CRITICAL — READ BEFORE EVERY ACTION

After every `git push`, you MUST complete all 3 steps before saying "done". No exceptions, no skipping:
1. **Notion** — append to Architecture & Decision Log (38770984-77e4-8125-a509-fe1325e133fd)
2. **CLAUDE.md** — update current state (tool count, positions); commit + push the change
3. **Memory** — update `memory/project_state.md` and `memory/feedback_rules.md`

Deployment is NOT complete until all 3 are done.

---

# AI Investment Management System

## Identity
Multi-asset portfolio manager Telegram bot (@AI_InvestorL_bot) on Railway.
Current theme: AI infrastructure. System is theme-agnostic.
GitHub: github.com/lliu722/ai-hedge-fund

## Current state (as of 2026-06-25)
- **44 tools** registered in agent
- 41 held positions (shares > 0) — portfolio with dollar P&L
- 57 watchlist names (shares = 0) — monitoring only
- 98 total in Notion Holdings DB

## Adding a new tool
1. Add @tool function to `src/tools/telegram_bot.py`
2. Add to `tools = [...]` list in `telegram_bot.py`
3. Commit and push — Railway auto-deploys in ~2 minutes

## Deploy
```
git add src/tools/telegram_bot.py [other files] && git commit -m "..." && git push origin main
```

## Notion IDs
- Architecture & Decision Log: `38770984-77e4-8125-a509-fe1325e133fd`
- Master Plan: `38870984-77e4-81bb-9eab-e4739d14ca4c`
- Holdings DB: `9dd63515-c7ae-4f2c-bbc9-a73c6c65bbd1`
- Trade Journal DB: `57ec5347-fc06-490d-9a60-e99e65a3d9bc`
- Master page: `38870984-77e4-818f-bd8b-ff154aa37a35`

## Rules
- Surgical edits preferred over full file rewrites
- Always commit and push after each build
- Never build without logging it
- All tools live in `telegram_bot.py` — not `bot_tools.py` (deleted)

## Architecture reference
→ See `docs/ARCHITECTURE.md` for: file map, V3 layer status, feature log, known gaps, full tool list.

## ⚠️ MANDATORY AFTER EVERY COMMIT+PUSH — NO EXCEPTIONS
Every deployment must close with all 3 of these steps before reporting done:
1. **Notion** — append entry to Architecture & Decision Log: what was built, key decisions, tool count
2. **CLAUDE.md** — update tool count and current state; commit + push
3. **Memory files** — update `memory/project_state.md` (tool count, new files) and `memory/feedback_rules.md` if new rules learned
