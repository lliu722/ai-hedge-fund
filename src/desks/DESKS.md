# DESKS.md — Trading Desk Architecture (Canonical Spec)

> **Purpose:** This is the canonical definition of the "desk" architecture for the AI Investment System.
> Claude Code should treat this file as the source of truth for what desks exist, what each desk does,
> and the shared interface every desk must implement. When desk behaviour changes, update THIS file in the
> same PR, and log the decision to the Notion Architecture & Decision Log before moving on.

---

## 1. Mental model

The system is organised as a set of **desks**. Each desk is a self-contained research+idea unit for one
slice of the market. Desks do **not** size positions or manage the book — they produce *ideas* with a
thesis and hand them to the **Portfolio / Risk Desk (PM layer)**, which is the only desk allowed to make
portfolio-level decisions.

```
                     ┌─────────────────────────────┐
                     │   Portfolio / Risk Desk      │  ← PM/CIO layer (orchestrator)
                     │   (sizes, approves, hedges)  │
                     └──────────────┬──────────────┘
                                    │ approves / rejects / sizes
        ┌──────────┬──────────┬─────┴────┬──────────┬──────────┬──────────┬──────────┐
        ▼          ▼          ▼          ▼          ▼          ▼          ▼          ▼
     Equity      Macro      Credit   Commod.    Options     Crypto    Event-Dr.   Quant
      L/S                                        / Vol                            /Syst.
   ── each desk emits IdeaCard(s) → PM/Risk layer ──
```

Quant/Systematic is special: besides emitting its own ideas, it provides **signals as a service** to the
other desks (rankings, regime flags, momentum, factor scores).

---

## 2. The Desk Contract (shared interface — implement ONCE)

Every desk (except the PM/Risk layer) follows the same lifecycle "spine". Implement this as a base class /
LangGraph subgraph that each desk extends. A desk only overrides the **desk-specific** functions in §4.

**Standard spine (applies to all desks):**

1. **Universe Definition** — declare the instruments/markets/themes this desk may cover.
2. **Data / Screening** — pull and screen the relevant data for this desk's universe.
3. **Research** — desk-specific analysis (see §4 for what each desk researches).
4. **Idea Generation** — produce candidate long/short/avoid/hedge ideas.
5. **Thesis Writing** — for each idea: why now, upside/downside, catalyst, time horizon, evidence, and
   the falsifier (what would prove it wrong).
6. **Trade Expression** — choose the instrument to express it (single name, ETF, basket, option, or "avoid").
7. **Idea Risk / Thesis Risk** — what could break this idea.
8. **Monitoring / Update Loop** — re-check whether the thesis is still playing out.
9. **Exit / Review Logic** — when to close, upgrade, downgrade, kill, or archive.
10. **Knowledge Base write** — persist notes, models, reviews to the report library.
11. **Output / Handoff** — emit ranked `IdeaCard`s to the PM/Risk layer.

### IdeaCard — the handoff contract (every desk emits this; PM/Risk consumes it)

```json
{
  "desk": "equity_ls",
  "ticker_or_instrument": "NVDA",
  "direction": "long | short | avoid | hedge",
  "conviction": 0.0,                 // 0–1
  "expression": "single_stock | etf | basket | option | pair | cash",
  "thesis": "string",
  "catalyst": "string",
  "time_horizon": "days | weeks | months",
  "upside": "string", "downside": "string",
  "falsifier": "what would prove this wrong",
  "thesis_risk": "string",
  "evidence_refs": ["kb://...", "url://..."],
  "monitor_triggers": ["earnings", "spread > X", "price < Y"],
  "created_at": "iso8601",
  "status": "new | live | review | closed | killed"
}
```

> **Rule:** Desks never set position size, weight, or portfolio allocation. Those fields are owned by the
> PM/Risk desk only. A desk that tries to size a position is a contract violation.

---

## 3. Desk registry

| # | Desk ID | Name | One-line role |
|---|---------|------|---------------|
| 1 | `equity_ls`   | Equity Long/Short      | Single-name & sector long/short equity ideas |
| 2 | `macro`       | Macro                  | Regime view → rates/FX/index/commodity expression |
| 3 | `credit`      | Credit                 | Credit cycle, spreads, default/refi risk → bond/loan allocation |
| 4 | `commodities` | Commodities            | Energy/metals/ags supply-demand → ETF/equity/inflation hedges |
| 5 | `options_vol` | Options / Volatility   | Hedging, defined-risk expression, vol & income strategies |
| 6 | `crypto`      | Crypto / Digital Assets| BTC/ETH/crypto-ETF/crypto-equity ideas, risk-capped |
| 7 | `event`       | Event-Driven           | Catalyst trades: earnings, M&A, regulation, litigation, products |
| 8 | `quant`       | Quant / Systematic     | Signals, screens, backtests + signal-as-a-service to other desks |
| 9 | `pm_risk`     | Portfolio / Risk (PM)  | Orchestrator: sizing, approval, exposure, drawdown, construction |

---

## 4. Desk-specific functions

> These are the functions UNIQUE to each desk, on top of the standard spine in §2.
> (Spine functions — Universe, Screening, Thesis, Expression, Monitoring, Exit, KB, Output — are NOT
> repeated here.)

### 1. Equity Long/Short — `equity_ls`
- Company Research — business model, revenue drivers, margins, financials, competitive position, management, narrative.
- Sector Research — intra-industry comparison; winners/losers, cyclicality, structural trends.
- Long Idea Generation — growth, earnings beats, re-rating, product cycles, secular tailwinds.
- Short / Avoid Idea Generation — deteriorating fundamentals, overvaluation, poor earnings quality, negative catalysts.
- Catalyst Tracking — earnings, guidance, revisions, launches, regulation, M&A, lawsuits.
- Valuation & Model Support — valuation models, peer comps, upside/downside cases, scenarios.
- Basket Construction — long-only / long-short / sector / thematic baskets.

### 2. Macro — `macro`
- Macro Regime Analysis — risk-on/off, inflationary/deflationary, recession/recovery, liquidity-driven.
- Central Bank Tracking — Fed, ECB, BOE, BOJ, PBOC: rate expectations, policy shifts, liquidity.
- Economic Data Monitoring — CPI, jobs, GDP, PMI, retail, housing, credit data.
- Rates View Formation — yields, curve, duration, real rates, hike/cut expectations.
- FX View Formation — rate differentials, growth divergence, flows, risk sentiment.
- Liquidity & Financial Conditions — dollar, credit conditions, reserves, issuance, QT/QE, funding stress.
- Cross-Asset Impact Analysis — translate macro view into equity/bond/credit/commodity/crypto effects.
- Scenario Analysis — base/bull/bear/shock around inflation, recession, policy, geopolitics.
- Macro Catalyst Calendar — CPI, payrolls, FOMC, ECB/BOE, GDP, refunding, elections.

### 3. Credit — `credit`
- Credit Cycle Analysis — expansion / late-cycle / stress / recovery / tightening.
- Spread Monitoring — IG, HY, loan spreads, CDS indices, credit-ETF performance.
- Default Risk Analysis — leverage, coverage, cash-flow weakness, maturity walls.
- Refinancing Risk Analysis — maturities, refi costs, capital-markets access.
- Balance Sheet Research — leverage, liquidity, FCF, debt structure, covenants, rating quality.
- Sector Credit Research — banks, real estate, energy, consumer, tech, industrials.
- IG / HY Allocation View — IG vs HY vs loans vs short-duration vs cash-like.
- Credit-Sensitive Equity Analysis — equities exposed to credit stress/refi/leverage.
- Rating / Downgrade Watch — rating changes, fallen-angel risk, upgrade candidates.
- Macro-Credit Linkage — connect spreads to rates, recession, liquidity, earnings, bank lending.

### 4. Commodities — `commodities`
- Supply-Demand Analysis — production, consumption, inventories, spare capacity, seasonality.
- Energy Market Research — crude, products, gas, LNG, power, OPEC, shale, energy security.
- Metals Market Research — precious & industrial metals, miners, real rates, industrial demand.
- Agriculture / Softs Research — weather, yields, export bans, food inflation, inventories.
- Inflation & Real-Asset Linkage — commodities vs inflation, real rates, FX, policy.
- Geopolitical Risk Tracking — wars, sanctions, shipping, export bans, OPEC, resource nationalism.
- Inventory & Curve Monitoring — inventories, curves, contango/backwardation, roll yield, storage.
- Commodity Equity Analysis — producers, miners, royalty/service companies.

### 5. Options / Volatility — `options_vol`
- Implied Volatility Analysis — IV vs HV vs event risk vs peers (cheap/expensive).
- Realized Volatility Analysis — actual movement vs market expectation.
- Volatility Regime Analysis — low/high/rising/falling/panic/complacency.
- Options Strategy Selection — covered calls, protective puts, spreads, collars, straddles, strangles, CSPs.
- Directional Options Ideas — bullish/bearish views with defined payoff.
- Hedging Strategy Design — protective puts, collars, index/sector/event hedges.
- Income Strategy Design — covered calls, cash-secured puts, conservative premium selling.
- Event Volatility Analysis — earnings/CPI/FOMC/launches where option pricing implies too much/little move.
- Greeks & Payoff Analysis — delta/gamma/theta/vega, breakeven, max loss/gain, probability range.
- Exit / Adjustment Logic — close, roll, take profit, cut loss, hedge, adjust before expiry.

### 6. Crypto / Digital Assets — `crypto`
- Liquidity Cycle Analysis — crypto vs global liquidity, dollar, real rates, risk appetite, ETF flows.
- BTC / ETH Core Research — narrative, adoption, network activity, supply, ETF demand, institutional positioning.
- On-Chain Data Analysis — wallets, exchange balances, stablecoin supply, volumes, staking, whale flows.
- ETF Flow & Institutional Demand — spot-ETF in/outflows, custody, fund positioning, TradFi participation.
- Regulation & Policy Tracking — enforcement, stablecoin rules, ETF approvals, exchange/tax/jurisdiction changes.
- Crypto Equity Analysis — exchanges, miners, payment, data-center, balance-sheet-crypto names.
- Narrative & Sentiment Tracking — halving, ETH upgrades, stablecoins, tokenization, DeFi, retail cycles.
- **Risk cap:** crypto desk ideas are hard-capped in risk by the PM layer regardless of conviction.

### 7. Event-Driven — `event`
- Catalyst Screening — scan for upcoming/developing events that move price/valuation/narrative.
- Earnings Event Analysis — dates, consensus, guidance risk, margins, revisions, beat/miss scenarios.
- M&A / Deal Analysis — deal spreads, approval/financing risk, completion probability.
- Regulation & Policy Event Analysis — antitrust, policy, tariffs, subsidies, licensing.
- Litigation / Legal Risk Analysis — lawsuits, investigations, settlements, patents, liabilities.
- Product / Technology Catalyst Analysis — launches, AI announcements, drug approvals, hardware cycles.
- Special Situations Research — spin-offs, restructurings, bankruptcies, activists, capital returns.
- Probability & Impact Assessment — likelihood × upside/downside per scenario.
- Market Expectations Check — desk view vs what's priced in (stock move, options, analysts, sentiment).
- Event Calendar Management — earnings, rulings, launches, investor days, deadlines, milestones.
- Post-Event Review Logic — actual vs thesis; exit/extend/reverse/upgrade/downgrade/archive.

### 8. Quant / Systematic — `quant`
- Data Pipeline Management — collect/clean/standardise price, fundamentals, estimates, macro, sentiment, alt data.
- Signal Research — momentum, value, quality, growth, revisions, vol, liquidity, sentiment, regime, positioning.
- Factor Analysis — which factors work/fail across regimes, sectors, caps, regions, asset classes.
- Screening & Ranking Models — weighted scoring to rank assets strongest→weakest.
- Backtesting — returns, drawdowns, hit rate, turnover, vol, regime performance.
- Model Validation — robustness across periods, costs, outliers, overfitting checks.
- Rule-Based Strategy Design — buy/sell/rebalance/filter rules, emotion-free.
- **Cross-Desk Signal Support** — serve rankings/regime/stress/trend/momentum signals to the other desks.
- Technical & Price Action Analysis — trend, MAs, breakouts, RS, S/R, volume, breadth.
- Sentiment & News Signal Analysis — news flow, revisions, social, call tone → measurable indicators.
- Signal Risk / Model Risk — overfitting, data errors, regime change, crowding, turnover/cost drag.
- Strategy Review Logic — keep/pause/modify/retire/rebuild on performance & regime fit.

### 9. Portfolio / Risk (PM layer) — `pm_risk`
> Orchestrator. Consumes IdeaCards from all desks; owns ALL sizing and portfolio decisions.
- Portfolio Mandate Definition — objective, risk tolerance, target return, universe, horizon, liquidity, allowed instruments.
- Capital Allocation — capital split across the 8 idea-generating desks.
- Position Sizing — size by conviction, vol, downside, liquidity, correlation, thesis quality.
- Risk Budgeting — risk limits per desk/asset class/sector/theme/region/strategy/position.
- Exposure Management — equity beta, duration, credit, FX, commodity, crypto, sector, factor exposure.
- Diversification Control — avoid over-dependence on one asset/theme/macro view/sector/factor/currency/regime.
- Correlation & Concentration Analysis — find hidden overlap (e.g. many trades all = long AI / long liquidity).
- Drawdown Control — track losses, enforce max-drawdown, de-risk in stress.
- Liquidity Management — ensure entry/exit/resize/hedge without excessive slippage.
- Hedging Framework — cash, index hedges, bonds, gold, options, inverse ETFs, reduced gross.
- Trade Approval / Rejection — approve/resize/delay/reject/hedge/watchlist each IdeaCard.
- Portfolio Construction — combine approved ideas into a balanced book.
- Rebalancing Logic — add/trim/rotate/exit/rebalance triggers.
- Performance Attribution — which desks/positions/sectors/factors help or hurt.
- Scenario & Stress Testing — recession, inflation spike, rate shock, spread widening, crash, oil spike, USD surge, crypto selloff.
- Risk Review / Kill Switch — conditions that force immediate de-risking.
- Portfolio Review Reports — performance, positioning, risks, changes, missed opportunities, next actions.

---

## 5. Suggested code mapping (adjust to current repo)

```
desks/
  __init__.py
  base.py            # Desk Contract: base class / LangGraph subgraph implementing the §2 spine
  contracts.py       # IdeaCard schema (pydantic), enums, validation
  equity_ls.py
  macro.py
  credit.py
  commodities.py
  options_vol.py
  crypto.py
  event.py
  quant.py           # also exposes signal-as-a-service API used by other desks
  pm_risk.py         # orchestrator; the only desk that sizes/approves
registry.py          # maps desk_id -> desk class; single source for "what desks exist"
```

- Each idea-desk implements `base.Desk` and overrides only its §4 functions.
- `pm_risk` is the LangGraph orchestrator node: fan-out to desks → collect IdeaCards → size/approve → output.
- `quant` is importable by other desks for signals; keep that as a clean read-only interface.
- Keep existing modules (`ficc.py`, `recommendations.py`, etc.) as data/tool providers the desks call —
  desks own the *logic*, those modules own the *data plumbing*.

---

## 6. Working rules for Claude Code (when editing desks)

1. **Surgical patches only** — change one desk/function at a time; no broad rewrites.
2. **Contract is law** — never let a desk set size/weight/allocation; that's `pm_risk` only.
3. **Every desk emits valid IdeaCards** — validate against `contracts.py` before handoff.
4. **Commit after every successful change**, with a message naming the desk + function touched.
5. **Log architecture decisions to the Notion Architecture & Decision Log before moving on.**
6. **Update this file in the same PR** whenever desk scope or the contract changes.
7. If a requested change conflicts with this spec, stop and flag it rather than silently diverging.
