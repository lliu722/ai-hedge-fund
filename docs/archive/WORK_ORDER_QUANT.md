# WORK_ORDER_QUANT.md — Quant Engine onto the desk model (on-demand)

> Executable work order for a literal coding agent. Same rules as `WORK_ORDER.md` Section 3.
> Goal: wrap the existing native V3 Quant factor engine onto canonical objects so it emits
> `Signal`s. ON-DEMAND ONLY — no dispatcher, no triggers, no live scheduler. Spec: `docs/desks/quant_engine.md`.

---

## RULES (re-read WORK_ORDER.md Section 3)
Read the docs first (ONBOARDING → AGENTS → BLUEPRINT → BUILD_LOG → docs/desks/quant_engine.md → this file). One task at a time. Commit after each with `type: description`. Update `docs/BUILD_LOG.md` (status + Decision Log line) in the SAME commit. Adapters declare `on_failure`; desk modules document `degrade_to`. Never touch `src/tools/scheduler.py`, `src/tools/telegram_bot.py`, `Procfile`, `pyproject.toml`. New code under `src/`; add `__init__.py` to new folders. Run each Verification before committing. If anything is unclear or conflicts — STOP and write a BLOCKED entry (WORK_ORDER.md Section 6).

**Grounding (already verified — do not re-investigate):** `src/tools/quant/factors.py` exposes `score_universe(tickers: list[str]) -> pandas.DataFrame` with columns: `ticker, name, sector, price, mom_12_1, rsi, inv_pe, quality, z_mom, z_quality, z_value, composite, signal`. The `signal` column is already one of `BUY` / `WATCH` / `AVOID`. This module imports clean (no scheduler/telegram side effects). Adapters MAY import it; desk features may not.

---

## TASK QE1 — QuantAdapter

**Preconditions:** `src/adapters/base.py` exists (Phase 1).

**Exact steps:**
1. Create `src/adapters/quant.py`.
2. `class QuantAdapter(Adapter)`. In `__init__` set `self.on_failure = "return empty list; caller reports quant unavailable"`.
3. `fetch(self, tickers: list[str]) -> list[dict]`:
   - Inside the method: `from src.tools.quant.factors import score_universe`.
   - `try`: `df = score_universe(tickers)`; return `df.to_dict("records")` (a list of row dicts).
   - `except Exception`: return `[]`.

**Output:** `src/adapters/quant.py`.

**Verification (needs network):**
```
poetry run python -c "from src.adapters.quant import QuantAdapter; r=QuantAdapter().fetch(['NVDA','MU','AMD']); print(type(r), len(r), (sorted(r[0].keys()) if r else 'empty'))"
```
Must print `<class 'list'>` and either rows with the factor columns or `empty` (empty is an acceptable degrade if the source is down).

**Build Log update:** Decision Log line:
`2026-06-29 · Added QuantAdapter wrapping score_universe → list[dict]; on_failure returns [] · src/adapters/quant.py`

---

## TASK QE2 — Quant desk: ranks → Signals

**Preconditions:** QE1 done. `src/core/objects.py` exists.

**Decision already made (do not change):** there is no dedicated quant `SignalType`. Use `SignalType.THEME` for a quant rank, with `source_desk="quant_engine"` and the rank detail in `summary`. (A dedicated enum is a future canonical-object change — out of scope.)

**Exact steps:**
1. Create folder `src/features/quant/` with empty `src/features/quant/__init__.py`.
2. Create `src/features/quant/desk.py`. Import `Signal`, `SignalType` from `src.core.objects` and `QuantAdapter` from `src.adapters.quant`.
3. Define `def run_quant_screen(tickers: list[str]) -> list[Signal]`:
   - `rows = QuantAdapter().fetch(tickers)`.
   - `degrade_to`: if `rows` is empty, return `[Signal(type=SignalType.DATA, subject_ref="UNIVERSE", severity=3, summary="quant screen unavailable — data source down", source_desk="quant_engine")]`. Document this in the module docstring.
   - Otherwise, for each `row` (already sorted best-first by `score_universe`), at index `i`:
     - `composite = row.get("composite") or 0.0`
     - `severity = max(1, min(10, round(5 + composite * 1.5)))` (maps the z-scored composite into 1–10).
     - `label = row.get("signal", "WATCH")`
     - `rsi = row.get("rsi")`
     - `caveat = ""`; if `label == "BUY"` and `rsi` and `rsi > 70`: `caveat = f" ⚠️ RSI overbought {round(rsi)}"`; elif `label == "AVOID"` and `rsi` and `rsi < 30`: `caveat = f" ⚠️ RSI oversold {round(rsi)}"`.
     - `summary = f"{label} · rank {i+1} · composite {composite:.2f} (mom {row.get('z_mom',0):.2f}/qual {row.get('z_quality',0):.2f}/val {row.get('z_value',0):.2f}){caveat}"`
     - build `Signal(type=SignalType.THEME, subject_ref=row["ticker"], severity=severity, summary=summary, source_desk="quant_engine")`.
   - Return the list of `Signal`s.

**Output:** `src/features/quant/__init__.py`, `src/features/quant/desk.py`.

**Verification (needs network):**
```
poetry run python -c "
from src.features.quant.desk import run_quant_screen
sigs = run_quant_screen(['NVDA','MU','AMD','TSM','AVGO'])
print(len(sigs), 'signals')
print(sigs[0].subject_ref, '|', sigs[0].summary)
"
```
Must print a count and a first signal whose summary begins with `BUY`/`WATCH`/`AVOID · rank 1 · composite ...` (or the single DATA degrade signal if the source is down).

**Build Log update:** In PART 2, Quant Engine "Migrated to model" 🔴→🟡. Decision Log line:
`2026-06-29 · Quant Engine desk: run_quant_screen converts factor ranks → THEME Signals (severity from composite, RSI caveat for overbought/oversold); degrade_to DATA signal · src/features/quant/desk.py`

---

## STOP HERE
Optimiser, backtest, rebalance, and inter-desk routing to House View / Risk Watch are later tasks (they need the dispatcher). When QE2 passes, the Quant Engine produces ranked `Signal`s on demand. Report and stop.
