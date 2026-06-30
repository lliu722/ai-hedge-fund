# Desk Spec · Coverage Analyst

> Operations manual for one desk. Architecture context: `../BLUEPRINT.md` §2 Desk 2. Status: `../BUILD_LOG.md`.
> This desk closes the system's biggest gap: **thesis-health watch / sell discipline.** Status: 🟡 partial (deep dive + valuation exist; proactive thesis watch 🔴 not built).

---

## 1 · Identity
**Responsibility:** maintain a live valuation and a live thesis on every *covered* name (held + watchlist), and re-test that thesis whenever new information arrives. It is the system's research analyst — it does not wait to be asked; it owns a coverage list and keeps a current view on each name.

**The one job that makes it matter:** tell the user *when a thesis is weakening or broken* — i.e. when to trim or sell — which the system currently never does proactively.

---

## 2 · Triggers
| Trigger | Type | Scope | Cadence |
|---|---|---|---|
| Weekly coverage sweep | schedule | all covered names | Sunday pre-digest |
| Earnings released | event (`Event:earnings`) | the reporting name | on event |
| Price move ≥5% in a day | event (`Signal:threshold`) | the moving name | on event |
| New report ingested mentioning a covered name | event (`Report`) | named names | on event |
| User asks ("is the NVDA thesis intact?", "should I sell MU?") | pull | named name | on demand |

---

## 3 · Functions operated (from the Spine)
Deep dive · Valuation · Thesis check · Earnings transcript + reaction · SEC filings.

---

## 4 · Inputs & outputs (canonical objects)
**Reads:** `Name`, `Position` (avg cost, P&L), the *saved* `Thesis`, recent `Event`s, recent `Report`s, price/valuation data (via adapters).
**Writes:** an updated `Thesis` (verdict + per-driver status + what changed), and — when the verdict degrades — a `Signal` and a `Recommendation`.

---

## 5 · The Thesis verdict state machine (the heart)
A saved `Thesis` has `drivers[]` (the pillars the case rests on), `risks[]`, `conviction`, `verdict`. On each run, evaluate **each driver** against fresh evidence and assign it a status: `holding` / `strained` / `invalidated`. Then:

| Verdict | Condition | Recommended action |
|---|---|---|
| **intact** | all drivers holding (minor strain ok); price action explainable by thesis | hold; update silently |
| **weakening** | ≥1 driver `strained` but none invalidated; OR price breakdown the thesis can't explain; OR a new material risk emerged | review → tighten stop / consider trim; **PUSH alert** |
| **broken** | ≥1 **core** driver `invalidated`; OR the original catalyst is dead; OR structural change (key customer lost, management strategy pivot, cycle turned) | exit / sell candidate; **PUSH alert** |

**Push rule:** when the verdict degrades from its last saved value (intact→weakening, →broken), push to the user. When stable or improving, update the `Thesis` record silently. This is the proactive sell discipline.

Example push: `⚠️ INTC — thesis was "AI-PC refresh + foundry turnaround". Driver 1 (AI-PC ramp) INVALIDATED: no ramp in last 2 calls, lost a major client to AMD. Verdict: BROKEN. Action: review for exit.`

---

## 6 · Sources — multi-lens (A / B / C)
Each lens is a **module in our code** (cribbed from the named repo, speaking our objects), not a live external framework. Each returns a `LensView`.

- **A — Fundamentals lens** *(pattern: TradingAgents fundamentals analyst, vendored)*
  Reads latest financials, growth, margins, balance sheet. Judges whether **fundamentals still support each thesis driver**.
  *Prompt sketch:* "Given this saved thesis and the latest fundamentals/earnings, for each driver state holding/strained/invalidated with one line of evidence. Flag any new fundamental risk."
- **B — Valuation lens** *(pattern: ai-hedge-fund Damodaran agent, vendored)*
  Computes intrinsic value vs price; margin of safety; implied forward return. Judges whether the name is **cheap / fair / expensive** *given* the thesis.
  *Prompt sketch:* "Estimate intrinsic value and margin of safety. Is the current price justified if the thesis holds? Return cheap/fair/expensive + implied return."
- **C — Thesis-pillar lens** *(house method, native)*
  Directly tests each saved driver against new evidence (the deep-dive logic). The primary input to the verdict.
  *Prompt sketch:* "For each saved driver, classify holding/strained/invalidated against the latest news, transcript, filings, and price action. Identify which drivers are core."

**Output shows all three, labelled** ("A (fundamentals) says… / B (valuation) says… / C (pillars) says…"), then a synthesis.

---

## 7 · Synthesis logic
1. **Verdict** is driven primarily by **C** (pillar status maps directly to the state machine in §5).
2. **A** confirms or contradicts C at the fundamental level (e.g. C says a driver holds, but A sees margins rolling over → downgrade to strained).
3. **B** sets the *action nuance* on an otherwise-intact thesis: intact + expensive → consider trim; weakening + cheap → hold and watch rather than sell.
4. **Disagreement is surfaced, never averaged.** If A and C conflict on a driver, the output states the conflict and defaults to the more cautious status pending the next data point.
5. Emit updated `Thesis` (verdict, per-driver status, conviction, last_reviewed) and, on degrade, a `Recommendation` (trim/sell + rationale citing the failed driver).

---

## 8 · Output template
```
{TICKER} — thesis {VERDICT}  (was {PREV_VERDICT})
Drivers:
  • {driver 1}: {holding|strained|invalidated} — {evidence}
  • {driver 2}: ...
A · Fundamentals: {one line}
B · Valuation: {cheap|fair|expensive}, {implied return} — {one line}
C · Pillars: {summary of pillar status}
Synthesis: {verdict} → {action}. {disagreements, if any}
```

---

## 9 · Failure & guards
- **on_failure:** if the transcript or fundamentals adapter is down → run on price + news + saved thesis only, label the output "data partial — {source} pending," and re-queue. Never skip a covered name silently.
- **degrade_to:** if the LLM call fails entirely → emit a price/P&L-only `Signal` ("could not refresh thesis for {name}") so the gap is visible.
- **Guards:** one full re-dive per name per day max; dedup pushes (don't re-alert the same verdict degrade within N days); a verdict can only auto-degrade — *upgrades* (broken→intact) require fresh confirming evidence, not a single good day.

---

## 10 · Module interfaces (for the builder)
```python
# all types are canonical objects from core/objects.py
def run_coverage(name: Name, thesis: Thesis, evidence: Evidence) -> CoverageResult: ...

def lens_fundamentals(name, thesis, evidence) -> LensView: ...   # A — vendored from TradingAgents
def lens_valuation(name, thesis, evidence)    -> LensView: ...   # B — vendored from ai-hedge-fund
def lens_pillars(name, thesis, evidence)      -> LensView: ...   # C — native

def synthesize(views: list[LensView], thesis: Thesis) -> Thesis: ...   # applies §5 + §7

# LensView = {source, per_driver: {driver_id: holding|strained|invalidated}, summary, signal}
# CoverageResult = {updated_thesis: Thesis, recommendation: Recommendation | None, pushed: bool}
```
Dependency rule: these never import data SDKs directly — `evidence` is assembled by a service that calls adapters. The desk depends inward on objects, not on `yfinance`.

---

## 11 · Edge cases
- **No saved thesis** → fall back to a fresh deep dive that *creates* the initial `Thesis` (drivers + verdict=intact), then watch from there.
- **Watchlist (no Position)** → run the same, but actions are "start / wait / pass," not "trim / sell."
- **Conflicting A vs C** → state both, take the cautious one, re-test next data point.
- **Thin coverage (FICC/crypto)** → run C only; mark A/B "not available for this asset class yet."

---

## 12 · Definition of done
- [ ] `Thesis` object + verdict enum exist in `core/objects.py`.
- [ ] Three lens modules return `LensView`; `synthesize` applies the state machine.
- [ ] Weekly sweep + earnings/5%-move triggers wired to the dispatcher.
- [ ] Verdict-degrade pushes an alert; stable verdicts update Notion silently.
- [ ] Runs end-to-end on one held name (e.g. MU) and one watchlist name, output matches §8.
- [ ] `on_failure` paths verified (kill the transcript adapter, confirm graceful degrade).

---

## 13 · Open questions for Louis (decide before/while building)

> **Status — provisional answers in force.** Louis has not given final answers yet. Until he does, `WORK_ORDER.md` Tasks 7–8 carry **explicit provisional defaults** and are the authoritative instruction for any agent building this desk. **Build to the WORK_ORDER, not to these questions.** This is NOT a conflict to STOP on — the WORK_ORDER wins; these notes record the defaults and stay open for Louis to override via a new work order.

1. **Core vs non-core drivers** — should *you* tag which thesis drivers are "core" (whose invalidation = broken), or should the desk infer it?
   - *Provisional default (WORK_ORDER Task 8):* read `driver.is_core` straight from the `Driver` object. Do not infer.
2. **Push threshold** — alert on every degrade, or only on →broken (and batch →weakening into the Sunday sweep)?
   - *Provisional default (WORK_ORDER Task 8):* push only on degrade to BROKEN; WEAKENING is silent (batched to the Sunday sweep by a later task).
3. **Trim vs sell** — do you want sizing guidance on a degrade (hand to House View), or just the verdict + flag?
   - *Provisional default (WORK_ORDER Task 8):* `Recommendation` carries `action` + `rationale` only; `size=""`. Sizing is House View's job, wired later.
