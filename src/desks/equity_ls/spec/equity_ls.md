# Equity Long/Short Desk (`equity_ls`)

---

## A. Core Functions

### A1. Theme & Name Discovery
Finds moving themes, sector rotations, supply-chain read-throughs, and new names to screen or deep dive.

### A2. Single-Name Deep Dive
Uses screening + TradingAgents + desk judgment to form a long/short/avoid conclusion on one company.

### A3. Earnings & Catalyst Response
Responds quickly to earnings, guidance, product launches, regulation, M&A, lawsuits, and major news.

### A4. Portfolio Decision Support
Tracks current holdings and converts thesis health, strategy view, and risk into hold/add/trim/sell *views* — not instructions. The view is emitted as an IdeaCard; `pm_risk` makes the actual sizing call.

### A5. Relative Value, Pair & Basket Ideas
Compares related names and creates better/worse expressions, pair trades, sector baskets, and thematic baskets.

---

## B. Infrastructure / Resources

### B1. Universe Definition
Defines eligible regions, instruments, priority tiers, restricted names, and coverage boundaries.

### B2. Data & Info Sources
Provides market data, fundamentals, news, earnings, ETF data, portfolio data, and internal calculations.

### B3. Portfolio Database
Stores holdings, average cost, position size, P&L, saved thesis, trade history, and portfolio exposure.

### B4. Report Library / Knowledge Base
Stores deep dives, TradingAgents outputs, thesis versions, earnings notes, valuation notes, and trade reviews.

### B5. TradingAgents Integration
Defines when to run TradingAgents, what context to pass, and how to store or compare its opinion.

---

## C. Cross-Function Risk Layer

Applies to all outputs before an IdeaCard leaves the desk.

- **Thesis Risk** — is the core thesis still intact?
- **Valuation Risk** — is upside too thin at current price?
- **Liquidity Risk** — is the name liquid enough to enter and exit?
- **Event Risk** — is there a near-term catalyst that changes the risk profile?
- **Concentration Risk** — are we already overweight this sector or theme?
- **Correlation Risk** — does this idea move with something already in the book?
- **Data Quality Risk** — are key data fields missing or stale?
- **Portfolio Relevance Check** — is this idea already expressed in the book?
