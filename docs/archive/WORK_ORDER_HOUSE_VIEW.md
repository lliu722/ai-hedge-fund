# WORK_ORDER_HOUSE_VIEW.md — House View (CIO) onto the desk model (on-demand)

> Executable work order for a literal coding agent. Same rules as `WORK_ORDER.md` Section 3.
> Goal: a House View desk that takes Coverage's `Thesis` + a `Position` + Quant/Risk `Signal`s
> and produces a `Recommendation` via A/B/C (personas · bull-bear · trader-sizing), plus the
> lightweight PM View button. ON-DEMAND ONLY — no dispatcher, no triggers, no live scheduler.
> Spec: `docs/desks/house_view.md`.

---

## RULES (re-read WORK_ORDER.md Section 3)
Read the docs first (ONBOARDING → AGENTS → BLUEPRINT → BUILD_LOG → docs/desks/house_view.md → this file). One task at a time. Commit after each with `type: description`. Update `docs/BUILD_LOG.md` (status + Decision Log line) in the SAME commit. Adapters declare `on_failure`; desk modules document `degrade_to`. Never touch `src/tools/scheduler.py`, `src/tools/telegram_bot.py`, `Procfile`, `pyproject.toml`. New code under `src/`; add `__init__.py` to new folders. Run each Verification before committing. If anything is unclear or conflicts — STOP and write a BLOCKED entry (WORK_ORDER.md Section 6).

**Grounding (already verified — do not re-investigate):**
- `src/tools/recommendations.py` exposes persona SYSTEM-prompt strings `CATHIE_WOOD`, `DRUCKENMILLER`, `DAMODARAN`, `LI_WEI`. It imports clean (no scheduler/telegram side effects). You MAY import these constants.
- `src/adapters/llm.py` exposes `LLMAdapter` with `fetch(prompt, system="", max_tokens=600, temperature=0.3) -> str` (returns "" on failure). Built in the Coverage phase.
- `size_position` lives in the LIVE `telegram_bot.py` — **do NOT import it.** Use the self-contained sizing rule in HV3.
- Canonical `Recommendation(name_ref, action: Action, size: str, rationale, persona, conviction: float, price_context, created_at)` and `Action` (buy/add/hold/trim/sell) are in `src/core/objects.py`.

---

## TASK HV1 — House View desk-local types

**Preconditions:** `src/core/objects.py` exists.

**Exact steps:**
1. Create folder `src/features/house_view/` with empty `src/features/house_view/__init__.py`.
2. Create `src/features/house_view/types.py` (use `from __future__ import annotations` + `dataclasses`). Define three dataclasses:
   - `PersonaCall`: `persona: str`, `action: str` (one of "buy"/"add"/"hold"/"trim"/"sell"), `conviction: str` (one of "High"/"Medium"/"Low"), `note: str = ""`.
   - `DebateView`: `bull: str = ""`, `bear: str = ""`, `lean: str = "balanced"` (one of "bull"/"bear"/"balanced").
   - `SizeView`: `size: str = ""`, `capped: bool = False`, `reason: str = ""`.

**Output:** `src/features/house_view/__init__.py`, `types.py`.

**Verification:**
```
poetry run python -c "from src.features.house_view.types import PersonaCall, DebateView, SizeView; print('house_view types ok')"
```
Must print `house_view types ok`.

**Build Log update:** Decision Log line:
`2026-06-29 · Added House View desk-local types (PersonaCall, DebateView, SizeView) · src/features/house_view/types.py`

---

## TASK HV2 — Lens A: persona panel

**Preconditions:** HV1 done. `LLMAdapter` exists.

**Exact steps:**
1. Create `src/features/house_view/lenses.py`. Import `json`; `Name`, `Thesis` from `src.core.objects`; `PersonaCall`, `DebateView` from `.types`; `LLMAdapter` from `src.adapters.llm`; the four persona prompts from `src.tools.recommendations`.
2. Add attribution comment: `# Lens A personas: ai-hedge-fund persona panel (MIT). Lens B debate + C trader: TradingAgents (Apache-2.0). See NOTICE.md.`
3. Define `def lens_personas(name: Name, thesis: Thesis) -> list[PersonaCall]`:
   - For each `(label, system)` in `[("Cathie Wood", CATHIE_WOOD), ("Druckenmiller", DRUCKENMILLER), ("Damodaran", DAMODARAN), ("Li Wei", LI_WEI)]`:
     - Build a user prompt: the ticker (`name.ticker`), the thesis summary, and its drivers; instruction: `"Give your call on this name as JSON only: {\"action\": one of buy/add/hold/trim/sell, \"conviction\": High/Medium/Low, \"note\": one sentence}."`
     - `raw = LLMAdapter().fetch(user_prompt, system=system, max_tokens=200)`.
     - If `raw` is empty → append `PersonaCall(persona=label, action="hold", conviction="Low", note="persona unavailable")` and continue (degrade).
     - `try: d = json.loads(raw)` → append `PersonaCall(persona=label, action=str(d.get("action","hold")).lower(), conviction=str(d.get("conviction","Medium")), note=d.get("note",""))`. On `json` error → append the degrade PersonaCall above.
   - Return the list (always length 4).

**Output:** `src/features/house_view/lenses.py` (with `lens_personas`).

**Verification (needs DEEPSEEK_API_KEY + network):**
```
poetry run python -c "
from src.core.objects import Name, Thesis, Driver
from src.features.house_view.lenses import lens_personas
calls = lens_personas(Name(ticker='MU'), Thesis(name_ref='MU', summary='memory upcycle', drivers=[Driver(id='d1', summary='DRAM pricing')]))
print(len(calls), 'persona calls'); print(calls[0].persona, calls[0].action, calls[0].conviction)
"
```
Must print `4 persona calls` and a first call line (actions may all be "hold" if the LLM is unavailable — that still proves the path).

**Build Log update:** Decision Log line:
`2026-06-29 · House View lens A: persona panel via LLMAdapter + recommendations.py prompts → 4 PersonaCalls (JSON), degrade to hold/Low · src/features/house_view/lenses.py`

---

## TASK HV3 — Lens B (bull/bear debate) + Lens C (trader sizing)

**Preconditions:** HV2 done.

**Exact steps:**
1. In `src/features/house_view/lenses.py`, add `def lens_debate(name: Name, thesis: Thesis) -> DebateView`:
   - Prompt: give the ticker + thesis; instruction: `"Argue both sides. Reply JSON only: {\"bull\": one sentence, \"bear\": one sentence, \"lean\": one of bull/bear/balanced}."`
   - `raw = LLMAdapter().fetch(prompt, system="You are a balanced analyst arguing both sides.", max_tokens=250)`.
   - Degrade: if empty or unparseable → `return DebateView(bull="", bear="", lean="balanced")`.
   - Else parse → `DebateView(bull=d.get("bull",""), bear=d.get("bear",""), lean=str(d.get("lean","balanced")).lower())`.
2. Add `def lens_trader(stance_action: str, position, risk_flags: list) -> SizeView` (import `SizeView` from `.types`; `Position`, `Signal` from `src.core.objects`):
   - Self-contained sizing rule (do NOT import size_position). Decide a base size string from the stance:
     - "buy" → `"5%"`, "add" → `"+2%"`, "hold" → `"hold"`, "trim" → `"-half"`, "sell" → `"exit"`.
   - **Risk cap (hard):** if any `Signal` in `risk_flags` has a `summary` that starts with `"CAP:"` and references this position's name (`position.name_ref in flag.subject_ref`), set `capped=True` and override an increasing action ("buy"/"add") size to `"no add — risk cap"`, `reason=that flag's summary`.
   - Return `SizeView(size=..., capped=..., reason=...)`.

**Output:** `lenses.py` updated with `lens_debate` and `lens_trader`.

**Verification:**
```
poetry run python -c "
from src.core.objects import Position, Signal, SignalType
from src.features.house_view.lenses import lens_trader
# capped case
flag = Signal(type=SignalType.RISK, subject_ref='NVDA', summary='CAP: NVDA already 63.0% (>10%) — do not add; trim or hold')
sv = lens_trader('buy', Position(name_ref='NVDA', shares=1), [flag])
print('capped:', sv.capped, '| size:', sv.size)
"
```
Must print `capped: True | size: no add — risk cap`.

**Build Log update:** Decision Log line:
`2026-06-29 · House View lens B (bull/bear debate, JSON, degrade balanced) + lens C (trader sizing rule, honours risk CAP as hard constraint, no size_position import) · src/features/house_view/lenses.py`

---

## TASK HV4 — synthesize → Recommendation

**Preconditions:** HV3 done.

**Exact steps:**
1. Create `src/features/house_view/synthesize.py`. Import `Recommendation`, `Action`, `Signal`, `Thesis` from `src.core.objects`; `PersonaCall`, `DebateView`, `SizeView` from `.types`.
2. Define `def synthesize_view(personas: list[PersonaCall], debate: DebateView, size: SizeView, quant: Signal | None, thesis: Thesis) -> Recommendation`:
   - Map actions to direction scores: `{"sell":-2,"trim":-1,"hold":0,"add":1,"buy":2}` (default 0 for unknown).
   - `persona_score = average of each persona's mapped action`.
   - `debate_adj = +1 if debate.lean=="bull", -1 if "bear", else 0`.
   - `quant_adj = +1 if quant and quant.summary.startswith("BUY") else (-1 if quant and quant.summary.startswith("AVOID") else 0)`.
   - `total = persona_score + 0.5*debate_adj + 0.5*quant_adj`.
   - Map `total` → `Action`: `>=1.5 BUY`, `>=0.5 ADD`, `>-0.5 HOLD`, `>-1.5 TRIM`, else `SELL`.
   - **Conviction:** collect persona action directions (sign of each mapped score). If all same sign → conviction float `8.0` (High); if mixed but no direct buy-vs-sell clash → `5.0` (Medium); if both a buy(+2) and a sell(-2) present → `3.0` (Low).
   - Build `rationale`: one line citing the dominant lean + the strongest bull or bear line; append a disagreement note if personas split (e.g. "personas split: 2 add / 2 hold"), else "unanimous".
   - Build the `Recommendation`: `name_ref=thesis.name_ref`, `action=<mapped>`, `size=size.size`, `rationale=<built>`, `persona="house_view"`, `conviction=<float>`, `price_context=(size.reason if size.capped else "")`.
   - Return it.

**Output:** `src/features/house_view/synthesize.py`.

**Verification (offline, pure):**
```
poetry run python -c "
from src.core.objects import Thesis
from src.features.house_view.types import PersonaCall, DebateView, SizeView
from src.features.house_view.synthesize import synthesize_view
personas = [PersonaCall('Wood','buy','High'), PersonaCall('Druck','add','High'), PersonaCall('Damo','add','Medium'), PersonaCall('Li','buy','High')]
rec = synthesize_view(personas, DebateView(lean='bull'), SizeView(size='5%'), None, Thesis(name_ref='MU'))
print(rec.action, '| conviction', rec.conviction, '| size', rec.size, '|', rec.rationale[:60])
"
```
Must print an `Action.BUY` (or `Action.ADD`) line with conviction `8.0` and size `5%` — without raising.

**Build Log update:** In PART 1 Decision, note house-view-on-model. Decision Log line:
`2026-06-29 · House View synthesize_view: persona direction avg + debate lean + quant tiebreak → Action; conviction from agreement; size from trader lens (risk-capped); disagreement surfaced · src/features/house_view/synthesize.py`

---

## TASK HV5 — run_house_view orchestrator + pm_view button

**Preconditions:** HV4 done.

**Scope limit:** do NOT wire to scheduler/telegram. Build the callables only.

**Exact steps:**
1. Create `src/features/house_view/desk.py`. Import `Name`, `Thesis`, `Position`, `Signal`, `Recommendation`, `Action` from `src.core.objects`; the three lenses from `.lenses`; `synthesize_view` from `.synthesize`; `LLMAdapter` from `src.adapters.llm`; `json`.
2. Define `def run_house_view(name: Name, thesis: Thesis, position: Position, quant: Signal | None = None, risk_flags: list[Signal] | None = None) -> Recommendation`:
   - `risk_flags = risk_flags or []`.
   - `personas = lens_personas(name, thesis)`; `debate = lens_debate(name, thesis)`.
   - Provisional stance for sizing: take the modal persona action (most common); `size = lens_trader(modal_action, position, risk_flags)`.
   - `return synthesize_view(personas, debate, size, quant, thesis)`.
   - `degrade_to`: document — if the LLM is unavailable every persona returns hold/Low and debate is balanced, so the desk still returns a HOLD `Recommendation` flagged low conviction rather than failing.
3. Define `def pm_view(context: str, position: Position) -> Recommendation`:
   - One LLM call: prompt includes `context` (on-screen text) + the position (`position.name_ref`, `position.shares`, `position.avg_cost`); instruction: `"You are the PM. Reply JSON only: {\"stance\": one of BUY/HOLD/REDUCE/PASS, \"conviction\": High/Medium/Low, \"rationale\": 2-3 sentences, \"key_risk\": one thing, \"action\": specific next step}."`
   - Map stance → `Action`: BUY→BUY, HOLD→HOLD, REDUCE→TRIM, PASS→HOLD.
   - Degrade: if empty/unparseable → `Recommendation(name_ref=position.name_ref, action=Action.HOLD, size="", rationale="PM view unavailable", persona="pm", conviction=0.0)`.
   - Else build `Recommendation(name_ref=position.name_ref, action=<mapped>, size="", rationale=d["rationale"], persona="pm", conviction=<High=8/Med=5/Low=3>, price_context=d.get("action",""))`.

**Output:** `src/features/house_view/desk.py`.

**Verification (offline degrade path is fine):**
```
poetry run python -c "
from src.core.objects import Name, Thesis, Driver, Position
from src.features.house_view.desk import run_house_view
rec = run_house_view(Name(ticker='MU'), Thesis(name_ref='MU', summary='upcycle', drivers=[Driver(id='d1', summary='DRAM')]), Position(name_ref='MU', shares=10, avg_cost=80))
print('action', rec.action, '| conviction', rec.conviction, '| size', rec.size)
"
```
Must print an `action Action.<...>` line without raising (HOLD/low if the LLM is offline — that proves the degrade path).

**Build Log update:** In PART 2, House View "Migrated to model" 🔴→🟡 and "Sources vendored" 🔴→🟡. Decision Log line:
`2026-06-29 · House View desk: run_house_view (A persona + B debate + C trader → synthesize → Recommendation) + pm_view button (one-call advisory verdict); degrade to HOLD/low when LLM down; not wired to triggers · src/features/house_view/desk.py`

---

## STOP HERE
Routing (Coverage degrade → House View, Risk cap delivery, Notion decision-journal write-back) and the Telegram button wiring all need the dispatcher / live code — separate work orders. When HV5 passes, House View produces a `Recommendation` and a PM verdict on demand. Report and stop.
