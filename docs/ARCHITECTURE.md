# AI Investment System — Architecture & Working Reference

Internal document. Updated after every meaningful build. Single source of truth for what's built, what each file does, and what's next.

---

## System Overview

A personal investment office running 24/7 as a Telegram bot (@AI_InvestorL_bot) on Railway. Built on DeepSeek V4 + LangGraph. Monitors 98 names (41 held, 57 watchlist), sends automated briefings and alerts, and responds to natural language queries.

**45 tools registered. ~8,500 lines across 27 files in src/tools/.**

---

## File Map

| File | What it does | Edit when you need to… |
|---|---|---|
| `telegram_bot.py` | LangGraph agent, all 39 @tool functions, bot polling loop | Add a new tool, change how the bot responds |
| `scheduler.py` | All scheduled jobs: morning briefing, close alerts, open alerts, breaking news, weekly digest, monthly 复盘 | Change timing, add a new automated message |
| `notion_holdings.py` | Reads Holdings DB from Notion (98 names, paginated). Write-back: add, buy, sell, rate, thesis, journal | Change how portfolio data is read or written |
| `llm.py` | Shared DeepSeek caller + Tavily search + clean_news() + fmt_snippet() | Change the LLM, tweak junk news filter, change API keys |
| `recommendations.py` | 4 investor personas: Cathie Wood, Druckenmiller, Damodaran, Li Wei. Parallel execution. | Change persona prompts, add/remove a persona |
| `deep_dive.py` | 9-section research report, ~45s. Injects saved notes + earnings history. | Change the deep dive structure or prompt |
| `proactive_analyst.py` | Mode 2: extracts new tickers from morning news, runs 4-section mini-dive automatically | Change proactive dive trigger logic or output format |
| `theme_radar.py` | 55-ETF Z-score scanner. Detects themes moving outside portfolio. All sectors. | Add/remove ETFs, change Z-score threshold |
| `prices.py` | yfinance + CoinGecko. Thread-safe cache. Handles HK/A-share/crypto tickers. | Fix price data issues, add new asset class |
| `themes.py` | THESIS_MAP (ticker → theme) + THEME_THESIS (thesis, signals, search queries per theme) | Add new themes, update thesis text |
| `read_through.py` | Industry read-through map: 14 trigger tickers → affected portfolio positions | Add new trigger tickers or relationships |
| `momentum.py` | GitHub commit velocity + arXiv paper count per theme | Add new repos/arXiv categories to track |
| `ficc.py` | FRED API: yield curve, credit spreads, FX pairs. Macro regime detector. | Add new FRED series, change regime logic |
| `risk.py` | Concentration, correlation, drawdown risk engine (Phase 1) | Change risk thresholds, add new risk metrics |
| `valuation.py` | DCF + comps valuation monitor | Change valuation methodology |
| `alert_config.py` | SQLite: custom price alerts, watchlist targets, alerted_today dedup table | Change alert persistence logic |
| `research_library.py` | SQLite: saves deep dives, earnings transcripts, manual notes. search + earnings history. | Change what gets saved or how it's retrieved |
| `catalyst_calendar.py` | Upcoming catalysts for held + buy-rated names | Add new event types |
| `earnings_calendar.py` | Parallel earnings date fetch, 10 workers | Change earnings date source |
| `news_fetcher.py` | Tavily news helper for individual tickers and macro queries | Change news fetch strategy |
| `sec_filings.py` | SEC EDGAR: 10-K, 10-Q, 8-K fetcher | Change filing types or parsing |
| `notify.py` | Telegram message sender. HTML parse mode. | Change message formatting or delivery |
| `api.py` | FastAPI health endpoint for Railway | Change health check behaviour |
| `quant/factors.py` | 3-factor model: momentum (12-1m, 40%), quality (ROE+margin, 30%), value (inv-PE, 30%). Z-scored cross-sectionally. 20 parallel yfinance workers. | Change factor weights or add new factors |
| `quant/signals.py` | Composite score → BUY/WATCH/AVOID (top/bottom 20%). Full screen + single-ticker breakdown. | Change signal cutoffs or output format |
| `quant/optimizer.py` | PyPortfolioOpt max-Sharpe + DiscreteAllocation (exact share counts). Ledoit-Wolf covariance shrinkage. | Change optimization objective or constraints |
| `quant/backtest.py` | Walk-forward monthly 12-1 momentum backtest. No external libs. Ann. return, vol, Sharpe, drawdown, beat-SPY %. | Change strategy or lookback |
| `quant/paper_trade.py` | SQLite paper portfolio (quant_paper_trades table). Open/close simulated positions with real-time P&L. | Change paper trade logic |
| `quant/universe.py` | Two-mode universe: 98 Notion names or S&P 500 (~500) fetched from Wikipedia. Session-cached. | Add/change universe sources |

---

## V3 Layer Status

### Layer 1 — Input

| Component | Status | Notes |
|---|---|---|
| Macro outlook (rates, inflation, central bank) | ✅ Built | FRED API — yield curve, credit spreads, HY OAS |
| Geopolitical pulse (4-geography) | ✅ Built | Tavily + DeepSeek, 1 sentence per geography |
| Equities — general market + sector rotation | ✅ Built | Sector ETF sweep in weekly digest |
| Equities — AI sector dedicated depth | ✅ Built | Morning briefing Section 3 |
| Equities — big banks | ✅ Built | Banks & Rates theme in sweep |
| Equities — other sectors / secular growth | ⚠️ Partial | Only covers held+watchlist names. Blind to sectors with zero exposure. |
| Commodities (gold, crude, copper, natgas, silver) | ✅ Built | yfinance futures |
| FICC — yield curve, credit spreads, FX | ✅ Built | FRED + yfinance. Daily vs background cadence still TBD. |
| Crypto (BTC, ETH, SOL) | ✅ Built | CoinGecko. Kept minimal. |

### Layer 2 — Morning Briefing

| Component | Status | Notes |
|---|---|---|
| Section 1: Filtered headline news | ✅ Built | Curated, events + read-through first if present |
| Section 2: What this means for portfolio + global markets | ✅ Built | Portfolio read-through by position name, global markets case by case |
| Section 3: Dedicated AI sector update | ✅ Built | Depth on AI Infra, Memory, Networking, Software & Data |
| Section 4: New theme discovery | ✅ Built | ETF Z-score radar (55 ETFs, all sectors) in Sunday digest + on-demand |
| Section 5: Portfolio overnight P&L | ✅ Built | First in message — all 41 held, sorted by move, with P&L % |
| Breaking news (does not wait for morning) | ✅ Built | DeepSeek score ≥8/10 threshold, fires immediately |

### Layer 3 — Research Report Library

| Component | Status | Notes |
|---|---|---|
| Auto-save system-generated deep dives | ✅ Built | SQLite research library |
| Auto-save earnings transcripts | ✅ Built | Auto-logged after every get_earnings_transcript call |
| Search across saved research | ✅ Built | search_research @tool |
| Manual notes / observations | ✅ Built | save_note @tool |
| PDF ingestion (broker research you bring in) | ❌ Not built | Framework TBD |
| Cross-reference report against current positions | ❌ Not built | Depends on PDF ingestion |

### Layer 4 — Deep Dive

| Component | Status | Notes |
|---|---|---|
| Mode 1: Reactive Q&A | ✅ Built | 9-section report, ~45s, auto-injects notes + earnings history |
| Supply chain read-through (14 triggers) | ✅ Built | NVDA → TSM → ASML etc. On-demand + morning briefing |
| Mode 2: Proactive analyst (system initiates) | ✅ Built | Extracts new names from morning news, 4-section mini-dive, max 2/day, 7-day cooldown |
| Report structure for pre-revenue names | ⏳ TBD | Pre-earnings names (ASTS, RKLB, OKLO) need different valuation framework |

### Layer 5 — Portfolio Construction & Decision Support

| Component | Status | Notes |
|---|---|---|
| 腾位置 (make room) | ✅ Built | Recommends what to trim to fund a new buy |
| Position sizing | ✅ Built | Fixed-fractional bands by conviction |
| Concentration tracking | ✅ Built | By name, sector, theme — risk engine Phase 1 |
| AI Shadow Portfolio | ✅ Built | Post-close: 3 personas each give 1 action call. 2nd message after close alert. All markets. |
| Shadow portfolio aggregation logic | ❌ Not built | Three personas disagree — no tiebreaker yet |
| Quant trading | ❌ Parked | 遥遥无期 |

### Layer 6 — Risk Management

| Component | Status | Notes |
|---|---|---|
| Concentration limits (per name / sector / theme) | ✅ Built | Phase 1 |
| Correlation clustering | ✅ Built | >0.7 correlation flagged as effectively one position |
| Drawdown tracking | ✅ Built | Per position + portfolio level |
| Macro regime detector | ✅ Built | FRED → RISK-ON / RISK-OFF / EASING / STAGFLATION / LATE CYCLE |
| Macro scenario stress test | ❌ Not built | Phase 2 — "what if AI falls 30%?" |
| VaR / tail risk | ❌ Not built | Phase 2 |
| Dynamic correlation (rolling 60-day) | ❌ Not built | Phase 2 |

### Layer 7 — 复盘 (Monthly Review)

| Component | Status | Notes |
|---|---|---|
| Monthly auto-push (1st of month, 9am HKT) | ✅ Built | Pulls closed trades from Notion Trade Journal |
| On-demand via bot | ✅ Built | get_monthly_review @tool |
| Win rate + avg P&L + best/worst + 3 lessons | ✅ Built | DeepSeek synthesis |
| Longitudinal bias tracking | ❌ Not built | Needs 3+ months of data first |

---

## Known Gaps (Audit Items)

| Gap | Priority | Notes |
|---|---|---|
| Exit framework | High | No systematic "is thesis still intact?" check for held positions. When to sell is almost entirely missing. |
| Shadow portfolio aggregation | Medium | Three personas give separate views — no tiebreaker logic |
| FICC wired into decisions | Medium | Macro regime exists but doesn't feed into shadow portfolio or 腾位置 |
| AI recommendation feedback loop | Medium | System recommends daily but doesn't track whether recommendations were acted on and were right |
| Behavioral bias tracking | Low | Needs 3+ months of 复盘 data first |

---

## What's Been Built (Feature Log)

- Morning briefing (7am HKT) — portfolio P&L first, 3 sections: Headlines / What This Means / AI Sector
- Sunday digest — weekly P&L, momentum, sector review, theme health scores, theme radar, AI picks
- Breaking news alerts every 2hrs — DeepSeek scores ≥8/10 only
- Market close alerts (US/HK/EU) — positions by category + synthesis + AI Shadow Portfolio (2nd message)
- Market open alerts (HK 9:20am HKT, US 9:20am ET) — pre-market movers, earnings today, news
- Portfolio advisor (腾位置) — what to trim to fund next buy
- Valuation monitor — DCF + comps
- Risk engine Phase 1 — concentration, correlation, drawdown
- Catalyst calendar — upcoming events for held + buy-rated names
- Notion write-back — add, buy, sell, reload, rate, thesis commands from bot
- Trade / Decision Journal — auto-log on buy, auto-close with P&L on sell
- Earnings reaction tool — post-earnings gut check
- Thesis-aware price alerts + recovery watch + peer valuation comparison
- Multi-theme analysis layer — THESIS_MAP + THEME_THESIS per theme
- Industry read-through map — 14 triggers → affected positions
- Li Wei HK/China analyst persona — 4th voice in AI stock picks
- Daily geopolitical pulse — 4-geography snapshot in briefing + on-demand
- GitHub + arXiv theme momentum tracker — leading developer signal
- Earnings transcript analysis — beat/miss headline + 5 sections (CEO tone, guidance, capex, Q&A)
- Portfolio P&L summary — weight %, today %, P&L % in monospace table
- Watchlist rating updater — "rate NVDA buy" → patches Notion Rating field
- Thesis write-back — "thesis NVDA ..." → patches Thesis field in Notion
- Position sizing calculator — fixed-fractional bands by conviction
- Research library — SQLite, auto-saves deep dives + earnings, search_research + save_note
- Custom alert thresholds — "alert NVDA 5" / "alert MU down 3" / "remove alert NVDA"
- Weekly P&L digest — unrealised + realised; get_pnl_summary on-demand
- Sector rotation monitor — 5-day ETF returns ranked, risk-off/risk-on signal
- Earnings surprise tracker — log + history; injected into deep dive
- Macro regime detector — FRED yield curve + HY OAS + Fed Funds → regime label
- Multi-portfolio support — Account field in Notion, switch_account tool
- Watchlist price targets — "target MRVL below 60", fires when price crosses
- Weekly theme health score — 0–10 per theme in Sunday digest + on-demand
- Junk news filter — clean_news() + fmt_snippet() in llm.py, applied everywhere
- AI Shadow Portfolio — 3 personas post-close, each gives 1 action call (2nd message)
- Monthly 复盘 — auto-pushed 1st of month + get_monthly_review on-demand
- Theme Radar — 55 ETF Z-score scanner, all sectors, Sunday digest + on-demand
- Proactive Analyst (Mode 2) — extracts new names from morning news, auto mini-dive
- V3 Quant (parallel system) — factor screen (momentum/quality/value), optimizer (PyPortfolioOpt), backtest (walk-forward 12-1 momentum), paper trading (SQLite). Universe: 98 Notion names or S&P 500 ~500 names.
- Keyboard redesign — 4-row inline keyboard: Portfolio/Watchlist, Briefing/Earnings, Deep Dive/Quant Screen, AI Picks/Explain

---

## Next to Build

- Shadow portfolio aggregation — tiebreaker when 3 personas disagree
- Layer 6 Phase 2 — macro scenario stress test ("what if AI falls 30%?")
- Exit framework — systematic thesis-intact check for held positions
- Layer 3 PDF ingestion — bring in external broker research

---

## Tool Count: 45

| Tool | What it does |
|---|---|
| deep_dive | 9-section research report on any ticker |
| get_price | Live price + change % |
| get_news | Latest news for tickers |
| get_earnings_calendar | Upcoming earnings dates |
| get_portfolio | Portfolio P&L table |
| get_watchlist | Watchlist names and ratings |
| get_market_briefing | On-demand morning briefing |
| get_sec_filings | SEC EDGAR 10-K/10-Q/8-K |
| get_ficc_data | Yield curve, credit spreads, FX |
| get_portfolio_advice | 腾位置 — what to trim to fund a buy |
| earnings_reaction | Post-earnings gut check |
| get_valuation | DCF + comps valuation |
| check_risk | Concentration, correlation, drawdown |
| get_catalyst_calendar | Upcoming catalysts |
| get_theme_analysis | Thesis health check per theme |
| get_theme_momentum | GitHub + arXiv signals per theme |
| get_geopolitical_pulse | 4-geography geo snapshot |
| get_read_through | Industry chain-reaction analysis |
| get_decision_journal | Trade log with P&L |
| get_earnings_transcript | Earnings call analysis |
| update_rating | "rate NVDA buy" → Notion |
| set_thesis | "thesis NVDA ..." → Notion |
| size_position | Position sizing calculator |
| search_research | Search saved research library |
| save_note | Save manual research note |
| manage_alerts | Set/remove/list custom price alerts |
| get_pnl_summary | Full P&L snapshot |
| get_sector_rotation | 5-day ETF sector rotation |
| log_earnings_surprise | Log earnings beat/miss |
| get_earnings_history | Earnings surprise history |
| get_macro_regime | Current macro regime from FRED |
| switch_account | Switch active portfolio account |
| list_portfolios | List all portfolio accounts |
| get_market_open_brief | Pre-market brief on-demand |
| manage_watchlist_target | Set/remove watchlist price targets |
| get_theme_health | Weekly theme health scores |
| get_monthly_review | Monthly 复盘 on-demand |
| get_theme_radar | All-sector ETF Z-score theme scan |
| get_proactive_dive | 4-section mini-dive on any ticker |
| get_quant_screen | Factor screen — rank 98 or ~500 names by composite score |
| get_quant_signal | Factor breakdown + rank for one ticker |
| get_quant_optimize | Max-Sharpe weights + exact share counts (PyPortfolioOpt) |
| get_quant_backtest | Walk-forward 12-1 momentum backtest, 1-5y |
| get_quant_paper | Paper portfolio P&L |
| manage_quant_paper | Open / close quant paper trades |

---

## Notion IDs

| Resource | ID |
|---|---|
| Architecture & Decision Log | 38770984-77e4-8125-a509-fe1325e133fd |
| Master Plan | 38870984-77e4-81bb-9eab-e4739d14ca4c |
| Holdings DB | 9dd63515-c7ae-4f2c-bbc9-a73c6c65bbd1 |
| Trade Journal DB | 57ec5347-fc06-490d-9a60-e99e65a3d9bc |
| Master page | 38870984-77e4-818f-bd8b-ff154aa37a35 |

---

*Last updated: 2026-06-25 — 45 tools, quant system live*
