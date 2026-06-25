# AI Investment System — V3 Working Roadmap

Internal reference. Updated after every meaningful build. Tracks what is done, what is TBD, and what is parked.

---

## Layer 1 — Input

Everything the system reads, monitors, and ingests.

| Component | Status | Notes |
|---|---|---|
| Macro outlook (rates, inflation, central bank) | ✅ Built | FRED API — yield curve, credit spreads, HY OAS |
| Geopolitical developments (4-geography pulse) | ✅ Built | Tavily, DeepSeek synthesis, 1 sentence per geography |
| Equities — general market direction | ✅ Built | In morning briefing Section 2 |
| Equities — sector-wise rotation | ✅ Built | Sector ETF sweep in weekly digest |
| Equities — AI sector (dedicated depth) | ✅ Built | Morning briefing Section 3 |
| Equities — big banks | ✅ Built | In theme sweep (Banks & Rates theme) |
| Equities — other sectors / secular growth | ⚠️ Partial | Only covers held+watchlist names. Blind to sectors with zero exposure. |
| Commodities (gold, crude, copper, natgas, silver) | ✅ Built | yfinance futures |
| FICC — yield curve, credit spreads, FX | ✅ Built | FRED + yfinance. What to surface daily vs background = still TBD |
| Crypto (BTC, ETH, SOL) | ✅ Built | CoinGecko. Kept minimal per original intent. |

---

## Layer 2 — Morning Briefing

| Component | Status | Notes |
|---|---|---|
| Section 1: Filtered headline news | ✅ Built | Curated, events + read-through first if present |
| Section 2: What this means for portfolio + global markets | ✅ Built | Portfolio read-through by position name, global markets case by case |
| Section 3: Dedicated AI sector update | ✅ Built | Depth on AI Infra, Memory, Networking, Software & Data |
| Section 4: New theme discovery | ✅ Built | ETF Z-score radar (55 ETFs, all sectors). Sunday digest + on-demand |
| Section 5: Portfolio overnight P&L | ✅ Built | First in message — all 41 held, sorted by move, with P&L % |
| Breaking news (does not wait for morning) | ✅ Built | DeepSeek score ≥8/10 threshold |

---

## Layer 3 — Research Report Library

| Component | Status | Notes |
|---|---|---|
| Auto-save of system-generated deep dives | ✅ Built | SQLite research library |
| Auto-save of earnings transcripts | ✅ Built | Auto-logged after every get_earnings_transcript call |
| Search across saved research | ✅ Built | search_research @tool |
| Manual notes / observations | ✅ Built | save_note @tool |
| PDF ingestion (broker research, macro notes) | ❌ Not built | Framework TBD. Key question: what does "system reads it" mean in practice? |
| Cross-reference report against current positions | ❌ Not built | Depends on PDF ingestion first |
| Delivery cadence | ⏳ TBD | Leaning on-demand. Scheduled drops risk becoming noise. |

---

## Layer 4 — Deep Dive

| Component | Status | Notes |
|---|---|---|
| Mode 1: Reactive Q&A (user asks, system answers) | ✅ Built | 9-section report, ~45s, auto-injects notes + earnings history |
| Supply chain read-through (14 triggers) | ✅ Built | NVDA → TSM → ASML etc. On-demand + morning briefing integration |
| Mode 2: Proactive analyst (system initiates) | ❌ Not built | System spots new name in news, runs mini-dive automatically. Trigger logic TBD. |
| Report structure update | ⏳ TBD | Pre-revenue names need different valuation framework (no P/E). |

---

## Layer 5 — Portfolio Construction & Decision Support

| Component | Status | Notes |
|---|---|---|
| Part 1: 腾位置 (make room) | ✅ Built | Recommends what to trim to fund a new buy |
| Part 1: Position sizing | ✅ Built | Fixed-fractional bands by conviction (high/medium/low) |
| Part 1: Concentration tracking | ✅ Built | By name, sector, theme — risk engine Phase 1 |
| Part 2: AI Shadow Portfolio | ✅ Built | Post-close: Cathie / Druck / Damodaran each give 1 action call. 2nd message after close alert. All markets. |
| Part 2: Shadow portfolio aggregation logic | ❌ Not built | Three personas give separate views. No tiebreaker yet. |
| Part 3: Quant trading | ❌ Parked | 遥遥无期. Not touching this yet. |

---

## Layer 6 — Risk Management

| Component | Status | Notes |
|---|---|---|
| Concentration limits (per name / sector / theme) | ✅ Built | Risk engine Phase 1 |
| Correlation clustering | ✅ Built | 1-year daily return history, >0.7 correlation flagged |
| Drawdown tracking | ✅ Built | Per position and portfolio level |
| Macro regime detector | ✅ Built | FRED yield curve + HY OAS + Fed Funds → RISK-ON/OFF/EASING/STAGFLATION/LATE CYCLE |
| Macro scenario stress test | ❌ Not built | "What if AI falls 30%?" — Phase 2 |
| VaR / tail risk | ❌ Not built | Phase 2 |
| Dynamic correlation (rolling 60-day) | ❌ Not built | Phase 2 — current model uses 1-year, misses regime shifts |

---

## Layer 7 — 复盘 (Monthly Review)

| Component | Status | Notes |
|---|---|---|
| Monthly auto-push (1st of month, 9am HKT) | ✅ Built | Pulls closed trades from Notion Trade Journal |
| On-demand via bot ("复盘", "monthly review") | ✅ Built | get_monthly_review @tool |
| Win rate + avg P&L + best/worst decision | ✅ Built | DeepSeek synthesis, honest and direct |
| 3 things to do differently | ✅ Built | Part of DeepSeek output |
| Longitudinal bias tracking | ❌ Not built | Requires 3+ months of 复盘 data before patterns emerge |

---

## Known Gaps (Audit Items)

Issues identified during V3 review that are not yet in any layer:

| Gap | Priority | Notes |
|---|---|---|
| Exit framework | High | No systematic "is the thesis still intact?" check for held positions. When to sell is almost entirely missing. |
| Shadow portfolio aggregation | Medium | Three personas disagree — no tiebreaker logic. Majority vote? Macro-regime weighted? |
| FICC wired into decisions | Medium | Macro regime exists but doesn't feed into shadow portfolio or 腾位置 recommendations |
| AI recommendation feedback loop | Medium | System recommends daily but doesn't track whether recommendations were acted on and were right |
| Behavioral bias tracking | Low | Needs 3+ months of 复盘 data first |

---

## Tool Count

**38 tools** as of 2026-06-25

| Added | Tool | Layer |
|---|---|---|
| 2026-06-25 | get_theme_radar | L2 Section 4 |
| 2026-06-25 | get_monthly_review | L7 |
| 2026-06-25 | (shadow portfolio via close alert) | L5 Part 2 |

---

*Last updated: 2026-06-25*
