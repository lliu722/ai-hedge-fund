# ⚠️ CRITICAL — READ BEFORE EVERY ACTION

After every `git push`, you MUST complete all 3 steps before saying "done". No exceptions, no skipping:
1. **Notion** — append to Architecture & Decision Log (38770984-77e4-8125-a509-fe1325e133fd)
2. **CLAUDE.md** — update "Built" and "Next to build"; commit + push the change
3. **Memory** — update `memory/project_state.md` and `memory/feedback_rules.md`

Deployment is NOT complete until all 3 are done.

---

# AI Investment Management System

## Identity
Multi-asset portfolio manager Telegram bot (@AI_InvestorL_bot) on Railway.
Current theme: AI infrastructure. System is theme-agnostic.
GitHub: github.com/lliu722/ai-hedge-fund

## File structure (src/tools/)
- telegram_bot.py — agent setup, callbacks, handle_message, bot loop. 36 tools registered.
- notion_holdings.py — Notion Holdings DB sync + write-back (add, buy, sell, rate, journal)
- scheduler.py — 7am briefing, Sunday digest, 2hr news alerts, US/HK/EU close alerts
- recommendations.py — Cathie Wood + Druckenmiller + Damodaran + Li Wei (HK/China) personas
- deep_dive.py — 8-section research report ~45s
- prices.py — yfinance + CoinGecko prices, thread-safe cache
- earnings_calendar.py — parallel fetch 10 workers
- ficc.py — FRED API: yield curve, credit spreads, FX
- valuation.py — DCF + comps valuation monitor
- risk.py — concentration, correlation, drawdown risk engine Ph1
- catalyst_calendar.py — upcoming catalysts for held + buy-rated names
- read_through.py — industry read-through map (14 trigger tickers → affected positions)
- momentum.py — GitHub commit velocity + arXiv paper count per theme
- themes.py — THESIS_MAP: ticker → theme mapping
- news_fetcher.py — Tavily news fetch helper
- notify.py — Telegram push notification helpers
- sec_filings.py — SEC EDGAR filing fetcher
- api.py — FastAPI health endpoint

## Adding a new tool
1. Add @tool function to telegram_bot.py (all tools live here now, not bot_tools.py)
2. Add to `tools = [...]` list in telegram_bot.py
3. Commit and push — Railway auto-deploys in ~2 minutes

## Deploy
git add src/tools/telegram_bot.py [other files] && git commit -m "..." && git push origin main

## Current state (as of 2026-06-25)
- 38 tools registered in agent
- 41 held positions (shares > 0) — portfolio with dollar P&L
- 57 watchlist names (shares = 0) — monitoring only
- 98 total in Notion Holdings DB

## Notion — read and log here
- Architecture & Decision Log: 38770984-77e4-8125-a509-fe1325e133fd
- Master Plan: 38870984-77e4-81bb-9eab-e4739d14ca4c
- Holdings DB: 9dd63515-c7ae-4f2c-bbc9-a73c6c65bbd1
- Trade Journal DB: 57ec5347-fc06-490d-9a60-e99e65a3d9bc
- Master page: 38870984-77e4-818f-bd8b-ff154aa37a35

## Rules
- Surgical edits preferred over full file rewrites
- Always commit and push after each build
- Never build without logging it

## ⚠️ MANDATORY AFTER EVERY COMMIT+PUSH — NO EXCEPTIONS
Every deployment must close with all 3 of these steps before reporting done:
1. **Notion** — append entry to Architecture & Decision Log (38770984-77e4-8125-a509-fe1325e133fd): what was built, key decisions, tool count
2. **CLAUDE.md** — update "Built" list and "Next to build" to reflect actual state; commit + push
3. **Memory files** — update memory/project_state.md (tool count, new files, next to build) and memory/feedback_rules.md if any new rules learned

If any of the 3 steps is skipped, the deployment is not complete.

## Built (all shipped)
- Morning briefing (7am) — prices, geo pulse, read-through, theme sweep
- Sunday digest — weekly P&L, momentum, sector review
- Breaking news alerts every 2hrs — DeepSeek scores 8+/10 headlines only
- Market close alerts (US/HK/EU) + post-market buy/trim/hold advice
- Portfolio advisor (腾空间) — what to trim to fund next buy
- Valuation monitor — DCF + comps
- Risk engine Phase 1 — concentration, correlation, drawdown
- Catalyst calendar — upcoming events for held + buy-rated names
- Notion write-back — add, buy, sell, reload, rate commands from bot
- Trade / Decision Journal — auto-log entries on buy, auto-close on sell with P&L
- Earnings reaction tool — post-earnings gut check
- Thesis-aware alerts + recovery watch + peer valuation comparison
- Multi-theme analysis layer
- Industry read-through map — 14 triggers → affected positions
- Li Wei HK/China analyst persona — 4th voice in AI stock picks
- Daily geopolitical pulse — 4-geography snapshot in briefing + on-demand
- GitHub + arXiv theme momentum tracker — leading developer signal
- Earnings transcript analysis — CEO tone, guidance, capex, Q&A extraction
- Portfolio dollar P&L summary — value, dollar P&L, sorted by size
- Watchlist rating updater — "rate NVDA buy" → patches Notion Rating field
- Thesis write-back — "thesis NVDA ..." → patches Thesis (Durable) field in Notion
- Position sizing calculator — size_position tool, fixed-fractional bands by conviction
- Research library — SQLite store, auto-saves deep dives + earnings, search_research + save_note tools
- Custom alert thresholds — `alert NVDA 5` / `alert MU down 3` / `remove alert NVDA` / `show alerts`
- Weekly P&L digest — unrealised (all positions vs cost, by sector) + realised (closed trades this week); `get_pnl_summary` tool for on-demand
- Sector rotation monitor — 5-day ETF returns ranked, risk-off/risk-on signal vs defensives
- Position notes in deep dive — saved notes + prior research auto-injected into every deep dive prompt
- Earnings surprise tracker — log_earnings_surprise + get_earnings_history tools; history injected into deep dive
- Macro regime detector — get_macro_regime() using FRED yield curve + HY OAS + Fed Funds → RISK-ON/RISK-OFF/EASING/STAGFLATION/LATE CYCLE
- Multi-portfolio support — Account field in Notion, set_active_account filter, switch_account + list_portfolios tools
- Market open alerts — HK 9:20am HKT + US 9:20am ET Mon–Fri; pre-market movers, earnings today, economic calendar; get_market_open_brief @tool on-demand
- Auto-log earnings from transcript — DeepSeek extracts beat/miss + surprise %s after every get_earnings_transcript call
- Sizing hints in open alert — >3% pre-market move shows $5k/$10k share count inline
- Watchlist price targets — `target MRVL below 60`; fires when price crosses; check_watchlist_targets in 30-min loop
- Weekly theme health score — 0–10 per theme (momentum + breadth) in Sunday digest + get_theme_health @tool

- Code refactor: shared llm.py (call_deepseek + tavily_search), zero inline API calls, -238 net lines, dead stubs deleted
- Market open alert fix — real pre-market data only (pre != prev check); earnings from earnings_calendar.py not Tavily; news with date-anchored query + junk domain filtering; no misleading session % when pre-mkt unavailable
- Morning briefing split — Portfolio (all held, sorted by move) + Watchlist movers (≥2% only, capped 15); fetches all 98 Notion names instead of hardcoded 20
- Junk news filter — central clean_news() + fmt_snippet() in llm.py; blocks tradingeconomics, investing.com, barchart, tradingview, calendar/schedule pages, markdown noise; applied to every Tavily call across all modules
- V3 roadmap — morning briefing restructured to 3 sections (Headlines / What This Means / AI Sector Update); close alert split into 2 messages (positions + AI Shadow Portfolio with Cathie/Druck/Damodaran each giving 1 action call); monthly 复盘 auto-pushed on 1st of month + get_monthly_review @tool on-demand
- Theme Radar — 55 ETF all-sector Z-score scanner (z>1.5, portfolio correlation <0.4); fires as 2nd message in Sunday digest + get_theme_radar @tool on-demand; works for biotech, consumer, energy, EM — not just tech
- V3 roadmap tracking doc — docs/V3_roadmap.md in repo; updated after each build

## Next to build
- Layer 2 Mode 2: proactive analyst — system spots new names in news and runs mini-dive automatically
- Layer 5 Part 2: shadow portfolio aggregation logic — tiebreaker when 3 personas disagree
- Layer 6 Phase 2: macro scenario stress test ("what if AI falls 30%")
- Known gap: exit framework — systematic "is thesis still intact?" check for held positions
