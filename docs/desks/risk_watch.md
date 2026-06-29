# Desk Spec · Risk Watch

> Operations manual for one desk. Architecture context: `../BLUEPRINT.md` §2 Desk 6. Status: `../BUILD_LOG.md`.
> Mechanical desk (single best method, not A/B/C), but **always-on and cross-cutting** — it watches every other desk's output. The system's brakes. Status: 🟡 partial (risk engine Phase 1 built: concentration / correlation / drawdown / regime; not on the desk model; Phase 2 VaR/stress 🔴).

---

## 1 · Identity
**Responsibility:** continuously watch portfolio exposure and decision risk — concentration, correlation, drawdown, regime — and flag *before* it hurts, including a hard cap on any size House View proposes.

**The one job that makes it matter:** every other desk pushes toward action; Risk Watch is the only one whose job is to say "no further." It is the brake that keeps a good thesis from becoming an oversized position.

---

## 2 · Triggers
| Trigger | Type | Scope | Cadence / exact condition |
|---|---|---|---|
| Continuous exposure sweep | schedule | whole book | daily + the Sunday risk section |
| On every decision | event (`Recommendation` from House View) | the proposed trade | fires whenever House View forms an actionable call — Risk checks it BEFORE it lands and returns a max-size / reduce flag |
| Market shock | event (`Signal:threshold` / regime change) | the book | fires on a large index/vol move or a macro-regime flip |
| Portfolio change | event (`Position` change) | the book | fires when a buy/sell updates Notion holdings — re-check concentration/correlation |
| User asks | pull | book or one name | "what's my biggest risk?" / "am I too concentrated in AI?" |

---

## 3 · Functions operated (from the Spine)
- **Concentration / correlation / drawdown** (BLUEPRINT Part 1 · Risk)
- **Macro regime detector** (Risk)
- **VaR / macro stress test** (Risk) — Phase 2, 🔴 not built

---

## 4 · Inputs & outputs (canonical objects)
**Reads:** all `Position`s (weights, P&L, cost basis), proposed `Recommendation`s from House View (to vet size before action), price/correlation history and macro data (via adapters), and Quant optimiser weights (to check the systematic book against limits).

**Writes:**
- risk `Signal`s — `type=RISK`, `subject_ref`=ticker or "PORTFOLIO", `severity` 1–10, `summary`=the specific breach, `source_desk="risk_watch"`.
- a **max-size / reduce flag** on a vetted `Recommendation` (the hard constraint House View must obey).
- a regime label `Signal` on a regime flip.

**Destination (every hop is explicit):**
- **Telegram** — risk alerts + the Sunday risk section.
- **Notion** — risk flags logged to the decision journal alongside the `Recommendation` they constrained (so 复盘 can see what risk said vs what happened).
- **→ House View** (inter-desk) — the max-size / reduce flag as a **hard cap** on any `Recommendation` size.
- **← Quant Engine** (inter-desk, inbound) — consumes optimiser weights to check the systematic book against limits.

This desk is **not** pull-only: it actively constrains House View on every decision and logs to the journal.

---

## 5 · Core logic
1. **Exposure map** — per name / sector / theme weight vs limits.
2. **Correlation clustering** — names with >0.7 correlation flagged as effectively one position (so "8 AI names" is really one bet).
3. **Drawdown** — per position + portfolio level vs thresholds.
4. **Regime** — FRED-driven label (RISK-ON / RISK-OFF / EASING / STAGFLATION / LATE CYCLE); a flip is itself a `Signal`.
5. **Decision vetting** — on a House View `Recommendation`: would the post-trade book breach a limit? If yes, return a max-size or reduce flag with the specific reason.
6. **(Phase 2) VaR / stress** — "what if AI falls 30%?" scenario P&L.
7. **Emit** — alerts to Telegram, flags to House View, logs to journal.

---

## 6 · Sources — single best implementation (mechanical desk, not A/B/C)
**TradingAgents role borrowed:** the **Risk Management Team / Portfolio Manager** risk-aggregation structure — as a *reference* pattern for how to aggregate and escalate risk, not as a live 3-debater committee (that complexity is deferred; ship the simpler engine first).

- **Native risk engine (V3 Phase 1)** — the shipped method: concentration / correlation / drawdown / regime.
- **TradingAgents risk-management team** — mode **reference** — risk-aggregation + escalation structure.
- **ai-hedge-fund risk manager** — mode **reference** — position-risk checks.

**No A/B/C.** Mechanical desk: evaluate the risk-aggregation structures, ship the best single engine. (Per BLUEPRINT Desk 6: the 3-debater pattern is "worth adapting once D2 and D4 are solid" — not now.)

---

## 7 · Synthesis logic (mechanical — aggregate and escalate, no debate)
1. Each check (concentration, correlation, drawdown, regime) produces a status; the **most severe** drives the headline flag (risk is a max, not an average — one red breach is not softened by four greens).
2. Correlated names are **collapsed into one effective position** before concentration is judged.
3. On decision vetting, the constraint is **binding**: Risk returns the cap, House View must size within it — Risk does not negotiate.
4. A regime flip is escalated once (deduped) and tags every subsequent risk flag with the current regime.
5. What could not be computed (data gap) is **flagged, never suppressed** — a missing correlation does not silently pass a name.

---

## 8 · Output template
```
🛡️ Risk Watch — {DAILY|DECISION|SHOCK|ASK}
Regime: {RISK-ON|RISK-OFF|EASING|STAGFLATION|LATE CYCLE}
Exposure: top name {x}% · top sector {y}% · top theme {z}%  {⚠️ if over limit}
Clusters: {TICKER+TICKER+… = one effective bet at w%}
Drawdown: {name/portfolio} {-x}%  {⚠️ if over threshold}
[Decision] {TICKER}: proposed {size} → CAP {max}%  ({reason, e.g. "AI theme already 38%"})
```

---

## 9 · Failure & guards
- **on_failure (historical/correlation data gap):** flag exactly what could not be computed ("correlation unavailable for {name}"), still emit every check that did run — **never suppress the whole risk read** because one input is missing.
- **on_failure (regime/FRED source down):** keep the last known regime, flag it stale, continue concentration/drawdown checks.
- **degrade_to:** if the full engine cannot run, fall back to raw concentration-by-weight from Notion `Position`s (the one check that needs no market data) so the brake never fully fails.
- **Cooldown:** alert dedup — the same breach is not re-alerted within its window; **max one regime-change alert per change**.
- **Dedup + max chain depth:** dedup risk `Signal`s by (subject, breach-type) within a window. Risk Watch is **cross-cutting** — it vets at the point of decision rather than starting chains. Its max-size flag attaches to an existing House View `Recommendation` (it does **not** add a hop — it constrains within the current hop), so it never extends a chain past the **3-hop cap**. A standalone risk alert (e.g. drawdown breach) is a hop-1 emission straight to Telegram.

---

## 10 · Module interfaces (for the builder)
```python
# all canonical types from core/objects.py
def run_risk_sweep(positions: list[Position]) -> list[Signal]: ...          # daily/continuous
def vet_decision(rec: Recommendation, positions: list[Position]) -> Signal: ...  # max-size/reduce flag
def detect_regime() -> Signal: ...                                          # FRED regime label
def stress_test(scenario: str, positions: list[Position]) -> Signal: ...    # Phase 2

# vet_decision returns a RISK Signal carrying the binding size cap House View must obey.
```
Dependency rule: price/correlation/macro data arrives via adapters; the desk never imports FRED/yfinance SDKs in its logic. Depends inward on objects.

---

## 11 · Edge cases
- **New book / too few positions** → concentration trivially high; flag context ("only 3 positions"), don't false-alarm.
- **Correlated cluster spanning sectors** (e.g. AI infra + AI power) → collapse into one effective bet even across sector labels.
- **Regime data stale** → use last known, flag staleness, don't block other checks.
- **House View proposes within limits** → return a green "no cap" flag (the decision still gets a recorded risk check).
- **Single-name drawdown but portfolio fine** → flag the name, not the book; no portfolio-level alarm.
- **Phase 2 stress requested before built** → respond "stress test not built yet," do not fabricate a VaR number.

---

## 12 · Definition of done
- [ ] Daily sweep produces the §8 exposure/cluster/drawdown/regime card.
- [ ] On a House View `Recommendation`, `vet_decision` returns a binding max-size flag that House View respects.
- [ ] Correlated names are collapsed before concentration is judged.
- [ ] Regime flip emits one deduped alert and tags subsequent flags.
- [ ] `on_failure` verified (kill correlation data → other checks still emit, gap flagged).
- [ ] `degrade_to` verified (no market data → raw concentration-by-weight still runs).
- [ ] Cross-cutting rule verified (Risk constrains within the decision hop, never extends the chain past 3).

---

## 13 · Open questions for Louis (decide before/while building)
1. **Concentration limits** — what are the hard caps (per name / sector / theme) Risk should enforce? Default placeholders: 10% name, 30% sector, 40% theme — confirm or set your own.
2. **Binding vs advisory** — should the max-size flag be a HARD cap House View cannot exceed (recommended), or a strong warning you can override? Default: hard cap on the system's own size, you (human) can always override manually.
3. **Phase 2 priority** — build VaR / macro stress test next, or keep Phase 1 (concentration/correlation/drawdown/regime) as the shipped scope for now? Default: Phase 1 is enough; defer Phase 2.
