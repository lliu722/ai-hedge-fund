# Master Desk Specifications — AI Investment Office

> **Status:** Living document. Refined as each desk is designed.
> Detail below the A/B/C function-name level belongs in each desk's own spec file.
> Implementation lives in `src/desks/` and will be wired here when each desk is built.

---

## Shared Contract (all desks)

Every idea-generating desk (1–8) emits `IdeaCard`s consumed by `pm_risk`.
Desks **never** set position size, weight, or allocation — that is `pm_risk` only.
Schema: `src/desks/contracts.py` · Base class: `src/desks/base.py` · Registry: `src/desks/registry.py`

---

## Desk 1 — Equity Long/Short (`equity_ls`)

### A. Core Functions
- **A1. Theme & Name Discovery** — finds moving themes, sector rotations, read-throughs, new names to screen
- **A2. Single-Name Deep Dive** — screening → TradingAgents → desk judgment → long/short/avoid conclusion
- **A3. Earnings & Catalyst Response** — reacts to earnings, guidance, M&A, regulation, major news
- **A4. Portfolio Decision Support** — thesis health + strategy view → hold/add/trim/sell *view* (not instruction)
- **A5. Relative Value, Pair & Basket Ideas** — better/worse expressions, pair trades, sector/thematic baskets

### B. Infrastructure / Resources
- **B1. Universe Definition** — eligible regions, priority tiers, restricted names, coverage boundaries
- **B2. Data & Info Sources** — price, fundamentals, news, earnings, factor scores, macro context
- **B3. Portfolio Database** — holdings, avg cost, P&L, thesis, trade history, exposure
- **B4. Report Library / Knowledge Base** — deep dives, agent outputs, thesis versions, trade reviews
- **B5. TradingAgents Integration** — when to run, what context to pass, how to store/compare output

### C. Cross-Function Risk Layer
- Thesis Risk · Valuation Risk · Liquidity Risk · Event Risk
- Concentration Risk · Correlation Risk · Data Quality Risk · Portfolio Relevance Check

---

## Desk 2 — Macro (`macro`)
> *Spec to be written when desk is built.*

### A. Core Functions
- **A1. Regime Identification**
- **A2. Central Bank & Rates View**
- **A3. FX View**
- **A4. Cross-Asset Translation**
- **A5. Scenario Analysis**

### B. Infrastructure / Resources
- *TBD*

### C. Cross-Function Risk Layer
- *TBD*

---

## Desk 3 — Credit (`credit`)
> *Spec to be written when desk is built.*

### A. Core Functions
- **A1. Credit Cycle Assessment**
- **A2. Spread Monitoring & View**
- **A3. Default & Refinancing Risk**
- **A4. Credit-Sensitive Equity Analysis**
- **A5. Rating Watch**

### B. Infrastructure / Resources
- *TBD*

### C. Cross-Function Risk Layer
- *TBD*

---

## Desk 4 — Commodities (`commodities`)
> *Spec to be written when desk is built.*

### A. Core Functions
- **A1. Supply-Demand Analysis**
- **A2. Energy Market Research**
- **A3. Metals Research**
- **A4. Inflation & Real-Asset Linkage**
- **A5. Commodity Equity Analysis**

### B. Infrastructure / Resources
- *TBD*

### C. Cross-Function Risk Layer
- *TBD*

---

## Desk 5 — Options / Volatility (`options_vol`)
> *Spec to be written when desk is built.*

### A. Core Functions
- **A1. Volatility Assessment**
- **A2. Hedging Strategy Design**
- **A3. Income Strategy Design**
- **A4. Directional Options Ideas**
- **A5. Event Volatility Analysis**

### B. Infrastructure / Resources
- *TBD*

### C. Cross-Function Risk Layer
- *TBD*

---

## Desk 6 — Crypto (`crypto`)
> *Spec to be written when desk is built.*

### A. Core Functions
- **A1. Liquidity Cycle Analysis**
- **A2. BTC & ETH Core Research**
- **A3. On-Chain Signal Analysis**
- **A4. Crypto Equity Analysis**
- **A5. Narrative & Regulation Tracking**

### B. Infrastructure / Resources
- *TBD*

### C. Cross-Function Risk Layer
- *TBD*

---

## Desk 7 — Event-Driven (`event`)
> *Spec to be written when desk is built.*

### A. Core Functions
- **A1. Catalyst Screening**
- **A2. Earnings Event Analysis**
- **A3. M&A / Deal Analysis**
- **A4. Regulation, Policy & Litigation**
- **A5. Special Situations**
- **A6. Post-Event Review**

### B. Infrastructure / Resources
- *TBD*

### C. Cross-Function Risk Layer
- *TBD*

---

## Desk 8 — Quant / Systematic (`quant`)
> *Spec to be written when desk is built.*

### A. Core Functions
- **A1. Factor Signal Generation**
- **A2. Screening & Ranking**
- **A3. Regime Detection**
- **A4. Backtesting & Strategy Validation**
- **A5. Technical & Price Action**
- **A6. Signal-as-a-Service** — serves signals to all other desks on request

### B. Infrastructure / Resources
- *TBD*

### C. Cross-Function Risk Layer
- *TBD*

---

## Desk 9 — Portfolio / Risk (`pm_risk`)
> Orchestrator. Consumes IdeaCards from all 8 desks. The **only** desk that sizes positions.
> *Full spec to be written when orchestrator is built.*

### A. Core Functions
- **A1. IdeaCard Triage** — approve / resize / delay / reject / watchlist
- **A2. Position Sizing** — conviction × vol-adjusted risk budget × downside × liquidity
- **A3. Portfolio Construction** — balanced book, diversification enforcement
- **A4. Risk Budgeting & Exposure Management** — limits per desk / sector / region / strategy
- **A5. Drawdown Control & Kill Switch**
- **A6. Hedging Framework**
- **A7. Performance Attribution**
- **A8. Rebalancing**

### B. Infrastructure / Resources
- *TBD*

### C. Risk Layer
- *TBD*

---

## Wiring Plan

```
docs/desks_master/MASTER.md     ← this file (map)
docs/desks_master/equity_ls.md  ← desk-level detail spec (when built)
docs/desks_master/macro.md      ← desk-level detail spec (when built)
...
src/desks/base.py               ← Desk ABC (built)
src/desks/contracts.py          ← IdeaCard schema (built)
src/desks/registry.py           ← desk registry (built)
src/desks/equity_ls.py          ← implementation (next)
...
src/desks/pm_risk.py            ← build last
```

Build order: `equity_ls` → `quant` (signal service) → `macro` → `pm_risk` → remaining desks.
