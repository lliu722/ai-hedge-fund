# Desk Spec · Quant Engine

> Operations manual for one desk. Architecture context: `../BLUEPRINT.md` §2 Desk 5. Status: `../BUILD_LOG.md`.
> Mechanical desk (single best method, not A/B/C). The systematic second opinion — factor ranks, optimisation, backtests — that feeds House View and Risk Watch. Status: 🟡 partial (V3 Quant built: screen / signal / optimiser / backtest / paper trade; not on the desk model).

---

## 1 · Identity
**Responsibility:** provide a systematic, rules-based second opinion on names and the book — factor ranks, optimiser weights, technical signals, and backtest support — independent of the narrative desks.

**The one job that makes it matter:** it is the unemotional counterweight. When House View's debate leans on a story, Quant says what the numbers and the tape actually rank — confirming, contradicting, or sizing the call.

---

## 2 · Triggers
| Trigger | Type | Scope | Cadence / exact condition |
|---|---|---|---|
| Scheduled factor screen | schedule | the declared universe (98 / ~500) | weekly (Sunday, feeds the digest) |
| Rebalance check | schedule | held book | monthly — optimiser weights vs current weights |
| New candidate from Idea Scout | event (`Signal` / promotion) | the candidate name | fires when Idea Scout promotes a name — Quant returns its factor rank as a House View input |
| House View asks for a read | pull (inter-desk) | the named name | House View requests rank/weight as a sizing input mid-call |
| User runs a screen / backtest | pull | universe or one name | on demand (`/quant`, "backtest momentum 3y") |

---

## 3 · Functions operated (from the Spine)
- **Quant screen** (BLUEPRINT Part 1 · Decision)
- **Quant optimise** (Decision)
- **Quant backtest** (Decision)

---

## 4 · Inputs & outputs (canonical objects)
**Reads:** the declared universe (`Name`s — 98 Notion names or ~500 S&P), price/factor data (via adapters), and current `Position`s (for rebalance: optimiser weights vs held weights).

**Writes:**
- one or more `Signal`s — `type=THEME` or a quant-rank signal, `subject_ref`=ticker, `severity`=composite score mapped 1–10, `summary`="rank N · score · BUY/WATCH/AVOID", `source_desk="quant_engine"`.
- on rebalance, a set of target weights expressed as `Signal`s per name (target vs current).

**Destination (every hop is explicit):**
- **Telegram** — the screen / rank / backtest result to the user.
- **→ House View** (inter-desk) — factor rank + optimiser weight as a **sizing/tiebreaker input** to a `Recommendation`.
- **→ Risk Watch** (inter-desk) — optimiser weights + concentration implied by a rank, so Risk can check the systematic book against limits.

This desk is **not** pull-only: its standing output feeds House View (sizing) and Risk Watch (exposure).

---

## 5 · Core logic
1. **Build universe** — resolve the declared `Name` set (98 Notion or ~500 S&P), session-cached.
2. **Factor model** — compute the 3-factor composite: momentum (12-1m, 40%), quality (ROE+margin, 30%), value (inv-PE, 30%), Z-scored cross-sectionally.
3. **Technical layer** — add the borrowed technical signals (MACD / RSI / trend) per name as a second systematic lens.
4. **Rank → label** — composite score maps to BUY / WATCH / AVOID (top/bottom quintiles).
5. **Optimise (on rebalance)** — max-Sharpe weights + discrete share allocation (Ledoit-Wolf shrinkage), capped to declared universe size.
6. **Backtest (on request)** — walk-forward 12-1 momentum; report ann. return, vol, Sharpe, drawdown, beat-SPY %.
7. **Emit** — ranks/weights/backtest to Telegram; rank+weight signals to House View and Risk Watch.

---

## 6 · Sources — single best implementation (mechanical desk, not A/B/C)
**TradingAgents role borrowed:** the **Technical Analyst** pattern (MACD/RSI/trend signal layer) — a systematic signal lens this system does not currently have. Not an opinion debate.

- **Microsoft Qlib** — mode **library** — factor-research + backtest patterns.
- **TradingAgents Technical Analyst** — mode **reference** — the MACD/RSI/trend signal patterns, reimplemented to emit our `Signal`s.
- **V3 Quant (native)** — the existing factor model / optimiser / backtester / paper-trade engine.

**No A/B/C.** Single shipped method: native V3 Quant factor model + Qlib-pattern backtest + a TradingAgents-pattern technical layer, all emitting our `Signal`s. "Multi-source" for a mechanical desk = evaluate implementations and ship the best, not present three.

---

## 7 · Synthesis logic (mechanical — combine signals, no opinion debate)
1. The **composite factor score** is the primary rank.
2. The **technical layer** is an overlay, not a vote: it can flag "rank says BUY but trend is broken" — surfaced as a caveat on the rank, not silently merged.
3. **Optimiser weights** are advisory targets, always subordinate to Risk Watch limits downstream (Quant proposes, Risk constrains).
4. Backtest output is **evidence about a strategy**, never a per-name call.
5. No averaging of opposing opinions — there are none; conflicts between factor rank and technical trend are reported as caveats.

---

## 8 · Output template
```
📐 Quant Engine — {SCREEN|RANK|REBALANCE|BACKTEST}
Top: {TICKER} score {x} (mom {a}/qual {b}/val {c}) → BUY
     {TICKER} … → WATCH
Bottom: {TICKER} … → AVOID
Technical caveat: {e.g. "NVDA top rank but RSI overbought"}
[Rebalance] Targets: {TICKER w%→w%}, … (max-Sharpe)
[Backtest] Ann {x}% · Sharpe {y} · MaxDD {z}% · beat SPY {n}%
```

---

## 9 · Failure & guards
- **on_failure (universe/price fetch fails):** run on the **cached universe**, flag staleness ("data as of {date}"); never silently rank on missing data.
- **on_failure (a factor cannot be computed for a name):** rank on the available factors, flag the name "partial factors," do not drop it.
- **degrade_to:** if the optimiser fails (singular covariance, etc.), fall back to equal-weight or the factor-rank ordering, flagged "optimiser degraded."
- **Cooldown:** scheduled screens run on their cadence; an Idea Scout-driven rank for the **same name** is not recomputed more than once per **24h** (use the cached rank).
- **Dedup + max chain depth:** dedup ranks by name within a run; cap the universe to the **declared size (98 / ~500)**. Quant is usually a **hop-2 input** (Idea Scout(1) → Quant(2) feeding House View, or House View pulls Quant mid-call). It feeds House View / Risk Watch but does not itself start a new opinion chain; chain cap **3 hops** respected — Quant stamps depth on emitted signals.

---

## 10 · Module interfaces (for the builder)
```python
# all canonical types from core/objects.py
def run_quant(scope: str = "screen", universe: str = "notion") -> QuantResult: ...

def factor_rank(universe: list[Name])    -> list[Signal]: ...   # native V3 factor model
def technical_layer(names: list[Name])   -> list[Signal]: ...   # TradingAgents Technical pattern (reference)
def optimise(held: list[Position])       -> list[Signal]: ...   # max-Sharpe target weights
def backtest(strategy: str, years: int)  -> BacktestReport: ...

# QuantResult = {ranks: list[Signal], weights: list[Signal] | None, backtest: BacktestReport | None}
```
Dependency rule: factor/price data arrives via adapters; the desk never imports yfinance/Qlib SDKs in its logic path beyond the adapter boundary. Depends inward on objects.

---

## 11 · Edge cases
- **Universe fetch returns < declared size** → run on what resolved, flag the shortfall.
- **Name with no price history** (recent IPO) → excluded from factor rank, flagged "insufficient history."
- **Rank disagrees with House View narrative** → emit the rank as-is; the disagreement is exactly the value Quant adds.
- **Backtest requested on too-short window** → refuse with "need ≥ N years," do not return a misleading stat.
- **Crypto / FICC names** → factor model is equities-tuned; flag "factor model not calibrated for this asset class," skip rather than mis-rank.

---

## 12 · Definition of done
- [ ] A scheduled screen produces ranks (BUY/WATCH/AVOID) matching §8 over the declared universe.
- [ ] An Idea Scout promotion gets a factor rank routed to House View.
- [ ] Rebalance produces optimiser target weights routed to House View + Risk Watch.
- [ ] Backtest returns ann/Sharpe/maxDD/beat-SPY without external libs.
- [ ] Technical caveat appears when factor rank and trend disagree.
- [ ] `on_failure` verified (kill the universe fetch → runs on cached, staleness flagged).
- [ ] Universe capped to 98 / ~500; chain depth stamped; cap 3 respected.

---

## 13 · Open questions for Louis (decide before/while building)
1. **Technical layer weight** — is MACD/RSI a *caveat only* (recommended) or should it adjust the composite rank itself? Default: caveat only, rank stays factor-driven.
2. **Rebalance authority** — should Quant push rebalance targets proactively (monthly), or only on request? Default: monthly proposal to House View, never auto-acted.
3. **Universe default** — Notion 98 or S&P ~500 as the standing screen universe? Default: Notion 98 for the weekly, ~500 on request.
