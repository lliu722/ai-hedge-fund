# Desk Spec · House View (CIO)

> Operations manual for one desk. Architecture context: `../BLUEPRINT.md` §2 Desk 4. Status: `../BUILD_LOG.md`.
> Opinion desk (the strongest A/B/C). It forms the system's own buy / sell / hold view, as if it ran the book. Status: 🟡 partial (persona panel + post-close shadow portfolio built; not on the desk model; bull/bear + trader not vendored).

---

## 1 · Identity
**Responsibility:** form the system's own actionable buy / sell / hold / trim view on a name — with conviction and size — by running a structured debate over the evidence Coverage produced.

**The one job that makes it matter:** Coverage says *what is true* about a name; House View says *what to do about it*. It is the CIO seat in software — it commits to a call so the user has a clear reference point to act on, override, or ignore. The human keeps the final trade.

---

## 2 · Triggers
| Trigger | Type | Scope | Cadence / exact condition |
|---|---|---|---|
| Post-close shadow portfolio | schedule | all held + buy-rated names | after each market close (US/HK/EU) — the full A/B/C run |
| Coverage verdict degraded | event (`Signal:thesis` from Coverage) | the degraded name | fires when Coverage reports a thesis →weakening or →broken (House View decides trim/sell/hold) |
| Quant signal flip | event (`Signal` from Quant Engine) | the name | fires when Quant rank crosses BUY/AVOID for a held or candidate name |
| Major event on a held name | event (`Event:earnings/fomc/threshold`) | the name | fires on earnings or a material move that warrants a fresh call |
| User asks for a call | pull | the named name | "should I add to MU?" / "buy or pass on AVGO?" — full A/B/C run |
| **PM View button** | pull (lightweight) | the name in the current message | inline `🧠 PM View` button on a deep dive / alert / answer → a one-shot PM verdict reading on-screen context + the Notion position, NOT a full debate re-run |

---

## 3 · Functions operated (from the Spine)
- **Conviction + sizing** (BLUEPRINT Part 1 · Decision)
- **腾位置 / portfolio advisor** — make room to buy (Decision)
- **Entry points** (tiered) (Decision)
- **House-view formation** (multi-persona) (Decision)

---

## 4 · Inputs & outputs (canonical objects)
**Reads:** the `Thesis` + valuation from Coverage (the evidence under debate), the current `Position` (held vs watchlist, cost basis, weight — to size and to run 腾位置), Quant `Signal`s (systematic second opinion), Risk Watch `Signal`s (max-size / reduce flags), and the saved persona frameworks.

**Writes:**
- one `Recommendation` — `{ name_ref, action(buy|add|hold|trim|sell), size, rationale, persona, conviction, price_context, created_at }`.
- on a degrade-driven sell/trim, also a `Signal` (`type=THESIS`, the action flag).

**Destination (every hop is explicit):**
- **Telegram** — the shadow-portfolio verdict card (full run) or the `🧠 PM Verdict` card (button).
- **Notion** — the `Recommendation` to the **decision journal** (only when it is an actionable call, so the journal records what the system advised vs what was done — the feedback loop for 复盘).
- **← Quant Engine** (inter-desk, inbound) — consumes factor rank/weight as a sizing input.
- **← Risk Watch** (inter-desk, inbound) — consumes max-size / reduce flags as a hard constraint on the recommended size.

House View is a **terminal** opinion desk: it consumes from Coverage/Quant/Risk and emits to the user + journal. It does not route an opinion onward to another opinion desk (that would exceed the chain cap).

---

## 5 · Core logic
1. **Gather evidence** — pull Coverage's `Thesis`+valuation, the `Position`, the Quant `Signal`, and Risk Watch's flags.
2. **Run A — persona panel** — each investor persona (Cathie / Druckenmiller / Damodaran / Li Wei) gives a call + conviction on this name.
3. **Run B — bull/bear debate** — a structured bull case vs bear case over the same thesis, surfacing the strongest argument each way.
4. **Run C — trader translation** — convert the resolved stance into an action + size, constrained by the `Position` (sizing bands, 腾位置 if a buy needs funding) and Risk Watch's max-size flag.
5. **Synthesise** (§7) → one `Recommendation`.
6. **Emit** — verdict card to Telegram; `Recommendation` to the decision journal if actionable.

**PM View (button) path:** skip A/B/C re-run. One LLM call with a PM persona prompt reading the on-screen context (the deep dive / alert / answer already in the thread) + the Notion `Position`, returning the tight `🧠 PM Verdict` card (§8). Advisory only.

---

## 6 · Sources — multi-lens (A / B / C, the core of this desk)
**TradingAgents roles borrowed:** **Bull Researcher + Bear Researcher** (feed B) and **Trader** (feed C). Persona panel (feed A) comes from ai-hedge-fund.

- **A — Persona panel** *(source: ai-hedge-fund investor-persona agents — Cathie Wood / Druckenmiller / Damodaran / Li Wei; mode **vendored**)* — diverse investor lenses, each a call + conviction.
- **B — Bull/Bear debate** *(source: TradingAgents Bull Researcher + Bear Researcher; mode **vendored**)* — structured disagreement before a call; forces the strongest case both ways.
- **C — Trader translation** *(source: TradingAgents Trader; mode **vendored** — note: only the *position/size translation* logic, NOT autonomous execution; the PM/execution seat stays human)* — turns stance into action + size.

---

## 7 · Synthesis logic (disagreement is the signal, never averaged)
1. **A and B set the stance.** Persona calls + the bull/bear debate resolve to a stance (buy / add / hold / trim / sell). If the personas split or bull and bear are both strong, the stance is the more cautious one **and the split is reported**.
2. **C sets the size**, constrained: never exceed Risk Watch's max-size flag; if it is a buy needing funding, run 腾位置 to name what to trim.
3. **Quant is a tiebreaker, not a vote** — when A/B are evenly split, a confirming Quant `Signal` breaks the tie; a contradicting one downgrades conviction and is stated.
4. **Disagreement becomes output** — the card always shows where the personas or bull/bear diverged ("Druckenmiller says add, Damodaran says expensive"). A unanimous call reads High conviction; a split call reads Medium/Low and says why.
5. Emit one `Recommendation` with `action`, `size`, `conviction`, `rationale` (citing the decisive argument), and `price_context`.

---

## 8 · Output template
**Full run (post-close / "give me a call"):**
```
🧠 House View — {TICKER}
Stance: {BUY|ADD|HOLD|TRIM|SELL} · Conviction: {High|Medium|Low}
Personas: Wood {call} · Druck {call} · Damodaran {call} · Li Wei {call}
Bull: {strongest bull line}
Bear: {strongest bear line}
Size: {e.g. "5%, fund by trimming INTC"} {— capped by Risk Watch if flagged}
Rationale: {2-3 sentences, the decisive argument}
Disagreement: {where the lenses split, or "unanimous"}
```
**PM View (button), tight:**
```
🧠 PM Verdict — {TICKER}
Stance: {BUY|HOLD|REDUCE|PASS} · Conviction: {High|Medium|Low}
Rationale: {2-3 sentences — what the PM is weighing}
Key risk: {one thing that could be wrong}
Action: {specific — e.g. "Add on a pullback to $X"}
```

---

## 9 · Failure & guards
- **on_failure (a persona or one lens errors):** run the remaining lenses, note the absence in the card ("Li Wei lens unavailable"), still produce a `Recommendation` — never block the whole call on one voice.
- **on_failure (Coverage thesis missing):** request a fresh Coverage run first; if unavailable, produce a PM-View-style verdict on price + position only, flagged "no current thesis — provisional."
- **degrade_to:** if the full A/B/C cannot run, fall back to the single-call PM View verdict so the user still gets a reference point, flagged "quick read, not full debate."
- **Cooldown:** **one full House View per name per session/day** (existing guard) — repeated triggers on the same name collapse into one call until the next session. The PM View button is exempt (it is on-demand and cheap) but dedups within a single message.
- **Dedup + max chain depth:** dedup `Recommendation`s by name within a session (don't journal the same call twice). House View is a **terminal** desk — it emits to the user + journal, never onward to another opinion desk. It typically sits at **hop 2 or 3**: Coverage(→) House View, or Idea Scout(1) → Coverage(2) → House View(3) which hits the **hard cap of 3**. House View must not trigger a further desk hop in that chain.

---

## 10 · Module interfaces (for the builder)
```python
# all canonical types from core/objects.py
def run_house_view(name: Name, thesis: Thesis, position: Position,
                   quant: Signal | None, risk_flags: list[Signal]) -> Recommendation: ...

def lens_personas(name, thesis)      -> list[PersonaCall]: ...   # A — ai-hedge-fund personas (vendored)
def lens_debate(name, thesis)        -> DebateView: ...          # B — TradingAgents bull/bear (vendored)
def lens_trader(stance, position, risk_flags) -> SizeView: ...   # C — TradingAgents trader sizing (vendored)
def synthesize_view(personas, debate, size, quant) -> Recommendation: ...  # §7

def pm_view(context: str, position: Position) -> Recommendation: ...  # button: one LLM call, advisory
```
Dependency rule: lenses get evidence as objects (from Coverage/Quant/Risk) and call the LLM via the LLM adapter; the desk never imports a data SDK. Depends inward on objects.

---

## 11 · Edge cases
- **Watchlist name (no Position)** → actions are start/wait/pass and size is "initial X%," not trim/sell.
- **Personas unanimous** → High conviction, short card, no "disagreement" line beyond "unanimous."
- **Risk Watch hard-flags the name** (over concentration) → size capped or forced to trim regardless of bullish stance; the cap is stated.
- **Buy with no room** → 腾位置 names the funding trim; if nothing is sensible to trim, downgrade to "watch, no room."
- **PM View button on a name not in Notion** → run on on-screen context only, note "not in book."
- **Conflicting Quant vs personas** → state it, lower conviction, do not hide it.

---

## 12 · Definition of done
- [ ] A full run on a held name produces a `Recommendation` matching the §8 full template, with all three lenses.
- [ ] The PM View button returns the tight `🧠 PM Verdict` card from on-screen context + Notion position in one LLM call.
- [ ] Actionable `Recommendation`s are written to the Notion decision journal; non-actionable ones are not.
- [ ] Risk Watch max-size flag is respected as a hard cap on size.
- [ ] Disagreement among personas / bull-bear is shown, never averaged away.
- [ ] `on_failure` verified (kill one persona → call still produced, absence noted).
- [ ] Terminal-desk rule verified (House View does not trigger another opinion desk; chain cap 3 respected).

---

## 13 · Open questions for Louis (decide before/while building)
1. **PM View scope** — should the button always be advisory-only (recommended), or also offer a one-tap "log this to the decision journal"?
2. **Auto-journal threshold** — journal every actionable `Recommendation`, or only High-conviction ones? Default: every actionable call.
3. **Sizing authority** — may House View suggest an exact size (e.g. "5%"), or only a direction + band, leaving the number to you? Default: suggest a size, always capped by Risk Watch.
