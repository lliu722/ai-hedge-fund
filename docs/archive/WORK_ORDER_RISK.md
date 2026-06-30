# WORK_ORDER_RISK.md — Risk Watch onto the desk model (on-demand)

> Executable work order for a literal coding agent. Same rules as `WORK_ORDER.md` Section 3.
> Goal: a Risk Watch desk that reads `Position` objects + live prices and emits risk `Signal`s
> (concentration, correlation, regime) plus a decision-vetting cap. ON-DEMAND ONLY — no
> dispatcher, no triggers, no live scheduler. Spec: `docs/desks/risk_watch.md`.

---

## RULES (re-read WORK_ORDER.md Section 3)
Read the docs first (ONBOARDING → AGENTS → BLUEPRINT → BUILD_LOG → docs/desks/risk_watch.md → this file). One task at a time. Commit after each with `type: description`. Update `docs/BUILD_LOG.md` (status + Decision Log line) in the SAME commit. Adapters declare `on_failure`; desk modules document `degrade_to`. Never touch `src/tools/scheduler.py`, `src/tools/telegram_bot.py`, `Procfile`, `pyproject.toml`. New code under `src/`; add `__init__.py` to new folders. Run each Verification before committing. If anything is unclear or conflicts — STOP and write a BLOCKED entry (WORK_ORDER.md Section 6).

**Grounding (already verified — do not re-investigate):**
- **Do NOT import from `src/tools/risk.py`.** It imports `PORTFOLIO_CATEGORIES` from the live `src/tools/scheduler.py` at module load, which drags in the running bot. The RiskDataAdapter below reimplements correlation via `yfinance` directly instead (an adapter is allowed the data edge).
- `src/tools/ficc.py` exposes `get_macro_regime() -> str` and imports clean (no scheduler/telegram side effects). The adapter may call it.
- `PriceAdapter` (`src/adapters/prices.py`, Phase 1) returns `{ticker: {"price": float, "change_pct": float}}`; a failed ticker is present but maps to `{}`.
- `Position` objects (from `PortfolioAdapter`) carry `name_ref`, `shares`, `avg_cost`. They do NOT carry live price — get it from `PriceAdapter`.

---

## TASK RW1 — RiskDataAdapter (correlation + regime)

**Preconditions:** `src/adapters/base.py` exists (Phase 1).

**Exact steps:**
1. Create `src/adapters/risk_data.py`.
2. `class RiskDataAdapter(Adapter)`. In `__init__` set `self.on_failure = "return empty correlations + UNKNOWN regime; caller degrades to concentration-only"`.
3. `fetch(self, tickers: list[str]) -> dict`:
   - Build the result `{"correlations": [], "regime": "UNKNOWN"}`.
   - **Regime:** `try: from src.tools.ficc import get_macro_regime; result["regime"] = get_macro_regime()` ; `except Exception: pass`.
   - **Correlation:** restrict to US-listed equities only — `us = [t for t in tickers if not any(t.endswith(s) for s in [".HK", ".SS", ".SZ", ".TW"]) and t not in {"BTC","ETH","SOL","MATIC","POL"}][:20]`.
     - `try`: `import yfinance as yf`; download ~1y daily closes for `us` (`yf.download(us, period="1y")["Close"]`); compute daily returns `.pct_change().dropna()`; `corr = returns.corr()`; collect every unique pair with `corr > 0.70` as `{"a": t1, "b": t2, "corr": round(float(c), 2)}` into `result["correlations"]`.
     - `except Exception: pass` (leave correlations empty).
   - Return `result`.

**Output:** `src/adapters/risk_data.py`.

**Verification (needs network):**
```
poetry run python -c "from src.adapters.risk_data import RiskDataAdapter; d=RiskDataAdapter().fetch(['NVDA','AMD','MU','TSM']); print('regime:', d['regime'], '| pairs:', len(d['correlations']))"
```
Must print a regime label (or `UNKNOWN`) and a pair count (0 is acceptable). Must not raise.

**Build Log update:** Decision Log line:
`2026-06-29 · Added RiskDataAdapter (regime via ficc.get_macro_regime + correlation>0.70 via yfinance, US equities only); on_failure → empty corr + UNKNOWN regime; deliberately avoids scheduler-coupled risk.py · src/adapters/risk_data.py`

---

## TASK RW2 — Risk Watch desk: sweep → Signals

**Preconditions:** RW1 done. `PriceAdapter` exists. `src/core/objects.py` exists.

**Decision already made (do not change):** concentration is judged by **single-name weight** in this version (theme/sector grouping needs the scheduler-coupled category map and is deferred). Name limit = **10%** (placeholder from spec §13 — do not change here).

**Exact steps:**
1. Create folder `src/features/risk/` with empty `src/features/risk/__init__.py`.
2. Create `src/features/risk/desk.py`. Import `Signal`, `SignalType`, `Position` from `src.core.objects`; `PriceAdapter` from `src.adapters.prices`; `RiskDataAdapter` from `src.adapters.risk_data`.
3. Define `def run_risk_sweep(positions: list[Position]) -> list[Signal]`:
   - If `positions` is empty: return `[Signal(type=SignalType.DATA, subject_ref="PORTFOLIO", severity=2, summary="no positions to assess", source_desk="risk_watch")]`.
   - `tickers = [p.name_ref for p in positions]`; `prices = PriceAdapter().fetch(tickers)`.
   - Compute market value per position: `mv = p.shares * (prices.get(p.name_ref, {}).get("price") or 0)`. `total = sum(mv)`.
   - `degrade_to`: if `total == 0` (no price data), return `[Signal(type=SignalType.DATA, subject_ref="PORTFOLIO", severity=3, summary="risk: price data unavailable — concentration not computed", source_desk="risk_watch")]`. Document in the module docstring.
   - **Concentration signals:** for each position, `weight = mv / total * 100`. If `weight > 10`: append `Signal(type=SignalType.RISK, subject_ref=p.name_ref, severity=min(10, round(weight/3)), summary=f"{p.name_ref} is {weight:.1f}% of book — single-name concentration (>10%)", source_desk="risk_watch")`.
   - **Correlation + regime:** `data = RiskDataAdapter().fetch(tickers)`.
     - For each pair in `data["correlations"]`: append `Signal(type=SignalType.RISK, subject_ref=f"{pair['a']}+{pair['b']}", severity=5, summary=f"{pair['a']} & {pair['b']} correlated {pair['corr']:.0%} — effectively one bet", source_desk="risk_watch")`.
     - Always append one regime signal: `Signal(type=SignalType.RISK, subject_ref="PORTFOLIO", severity=2, summary=f"macro regime: {data['regime']}", source_desk="risk_watch")`.
   - Return all signals.

**Output:** `src/features/risk/__init__.py`, `src/features/risk/desk.py`.

**Verification:**
```
poetry run python -c "
from src.core.objects import Position
from src.features.risk.desk import run_risk_sweep
ps = [Position(name_ref='NVDA', shares=100, avg_cost=50), Position(name_ref='MU', shares=10, avg_cost=80)]
sigs = run_risk_sweep(ps)
for s in sigs: print(s.subject_ref, '|', s.summary)
"
```
Must print one line per signal without raising (a regime line is always present; concentration/correlation lines depend on live prices).

**Build Log update:** In PART 2, Risk Watch "Migrated to model" 🔴→🟡. Decision Log line:
`2026-06-29 · Risk Watch desk: run_risk_sweep emits RISK Signals (single-name >10% concentration, >0.70 correlation pairs, macro regime); degrade_to DATA signal when no prices · src/features/risk/desk.py`

---

## TASK RW3 — Decision vetting (the binding cap)

**Preconditions:** RW2 done.

**Decision already made (do not change):** to avoid parsing free-text `Recommendation.size`, this version vets by **current weight only**: if the name is already over the 10% limit and the action adds to it, return a CAP signal; otherwise return a green within-limits signal.

**Exact steps:**
1. In `src/features/risk/desk.py`, add `def vet_decision(rec, positions: list[Position]) -> Signal` (import `Recommendation`, `Action` from `src.core.objects`).
2. Compute the current weight of `rec.name_ref` using the same price/market-value logic as RW2 (reuse a small helper if you like).
3. If `rec.action` is `Action.BUY` or `Action.ADD` and the current weight `> 10`: return `Signal(type=SignalType.RISK, subject_ref=rec.name_ref, severity=8, summary=f"CAP: {rec.name_ref} already {weight:.1f}% (>10%) — do not add; trim or hold", source_desk="risk_watch")`.
4. Otherwise: return `Signal(type=SignalType.RISK, subject_ref=rec.name_ref, severity=1, summary=f"{rec.name_ref} within limits ({weight:.1f}%) — no cap", source_desk="risk_watch")`.

**Output:** `src/features/risk/desk.py` updated.

**Verification:**
```
poetry run python -c "
from src.core.objects import Position, Recommendation, Action
from src.features.risk.desk import vet_decision
rec = Recommendation(name_ref='NVDA', action=Action.ADD)
print(vet_decision(rec, [Position(name_ref='NVDA', shares=100, avg_cost=50)]).summary)
"
```
Must print a line starting with `CAP:` or `NVDA within limits` without raising.

**Build Log update:** In PART 1 Risk section, note the cap is built. Decision Log line:
`2026-06-29 · Risk Watch vet_decision: binding cap by current weight — buy/add to a >10% name returns CAP signal, else within-limits; size-string parsing deliberately avoided · src/features/risk/desk.py`

---

## STOP HERE
Sector/theme concentration (needs the category map), drawdown, VaR/stress (Phase 2), and routing the cap into House View all come later (the routing needs the dispatcher). When RW3 passes, Risk Watch produces a risk sweep + a binding decision cap on demand. Report and stop.
