# Desk Spec · Idea Scout

> Operations manual for one desk. Architecture context: `../BLUEPRINT.md` §2 Desk 3. Status: `../BUILD_LOG.md`.
> Opinion desk (multi-feed A/B/C). It hunts **outside** the book — new names, forming themes, leading signals — and hands the best ones to Coverage to start coverage. Status: 🟡 partial (theme radar + proactive analyst built; not on the desk model).

---

## 1 · Identity
**Responsibility:** hunt outside the current book for new names, forming themes, and leading signals, and surface the best candidates with a "why now" so Coverage can pick them up.

**The one job that makes it matter:** the book only grows if something feeds it new ideas *before* they are obvious — Idea Scout is the system's forward radar, positioning ahead of the catalyst (the north-star "proactive beats reactive").

---

## 2 · Triggers
| Trigger | Type | Scope | Cadence / exact condition |
|---|---|---|---|
| Daily pre-briefing scan | schedule | full hunt universe | every morning before the 7am briefing |
| Weekly deep scan | schedule | full hunt universe | Sunday, feeds the digest |
| Theme radar Z-score spike | event (`Signal:theme`) | the moving theme | fires when a theme's ETF Z-score crosses the radar threshold |
| GitHub/arXiv momentum spike | event (`Signal:theme`) | the theme | fires when developer/research momentum for a theme jumps over its baseline |
| Repeated mention of an uncovered name | event (`Signal:news` from Research Librarian) | the named ticker | fires when the same uncovered name is routed in ≥N times within a 7-day window |
| Unusual move on a non-book name | event (`Signal:threshold`) | the moving name | fires when a watchlist/uncovered name moves ≥ the move threshold in a day |
| User focus area | pull | a theme/sector | on demand ("find me names in data-center power") |

---

## 3 · Functions operated (from the Spine)
- **Macro & geo scan** (BLUEPRINT Part 1 · Intelligence)
- **Sector / theme monitor** (BLUEPRINT Part 1 · Intelligence)
- **Catalyst calendar** (BLUEPRINT Part 1 · Monitoring)

Note: the Spine's **News filter** function is owned by the briefing desks (Morning-Briefing / Breaking-News), not Idea Scout. Idea Scout consumes news and sentiment as *analytical lenses* (its A/B feeds, §6) and receives breaking-news `Signal`s from those desks — it does not operate the News-filter function itself.

---

## 4 · Inputs & outputs (canonical objects)
**Reads:** the coverage list (`Name`s, to know what is already in the book), theme/momentum data and screener output (via adapters), inbound `Signal`s (theme radar, momentum, Librarian's uncovered-name mentions, threshold moves), and the catalyst calendar (`Event`s).

**Writes:**
- candidate `Name`s — a `Name` not yet in the book (`{ticker, exchange, asset_class, sector, theme[]}`). (NOTE: the blueprint calls this a "Candidate"; expressed here as a `Name` + its `Signal`, since `Candidate` is not a §3.1 canonical object — see open question 1.)
- one or more `Signal`s per candidate — `type=THEME` or `NEWS`, `subject_ref`=ticker, `severity`=research priority 1–10, `source_desk="idea_scout"`, summary = the "why now".

**Destination (every hop is explicit):**
- **Telegram** — the candidate list in the morning/Sunday message.
- **Notion** — candidates written to the watchlist-candidates DB.
- **→ Coverage Analyst** (inter-desk) — when a candidate clears the promotion bar (§7), route it so Coverage starts initial coverage (fresh deep dive → creates the first `Thesis`).
- **→ Research Librarian** (inter-desk, pull) — request an evidence pack on a candidate before promoting it ("what do we have filed on X?").

This desk is **not** pull-only: its standing job is to promote candidates to Coverage and to pull evidence from the Librarian.

---

## 5 · Core logic
1. **Gather feeds** — run the three lenses (§6) over the hunt universe: news (A), sentiment/crowding (B), theme/momentum (C), with OpenBB screeners as the data floor.
2. **Assemble candidates** — each surfaced ticker gets a feed-agreement count (how many of A/B/C flagged it) and a "why now" line.
3. **Filter the book** — drop tickers already covered (held/watchlist with a thesis); a covered name that re-surfaces is routed to Coverage as a *re-test*, not a new candidate.
4. **Score research priority** — agreement across feeds + catalyst proximity (from the calendar) + theme health → priority 1–10.
5. **Promote** — candidates over the bar (§7) route to Coverage; the rest are listed as "watch."
6. **Emit** — candidate list to Telegram/Notion, promotions to Coverage.

---

## 6 · Sources — multi-lens (A / B / C, signal feeds)
**TradingAgents roles borrowed:** **News Analyst** (feed A) + **Sentiment Analyst** (feed B). Per the blueprint, Idea Scout's "multi-source" means multiple *signal feeds* that can disagree on whether a name is worth surfacing — not three opinions on one held name.

- **A — News feed** *(pattern: TradingAgents News Analyst, mode reference)* — what is happening around a name/theme right now; sets **urgency**.
- **B — Sentiment / crowding feed** *(pattern: TradingAgents Sentiment Analyst, mode reference)* — is the name early or already crowded; sets the **crowding caveat**.
- **C — Theme / momentum feed** *(native: your theme radar + GitHub/arXiv momentum)* — the structural, leading signal; sets the **thesis frame** ("where it fits").
- **Data floor:** **OpenBB** screeners — mode **library** — the universe and raw metrics the three feeds read.

---

## 7 · Synthesis logic (disagreement is surfaced, never averaged)
1. **Promotion bar:** a candidate flagged by **≥2 of the 3 feeds** clears the bar and routes to Coverage; a single-feed flag is listed as "watch" only.
2. **Precedence when feeds disagree:** **C (theme/momentum)** sets the thesis frame; **A (news)** sets urgency; **B (sentiment)** sets the crowding caveat. They are layered, not voted.
3. **Disagreement becomes output:** when **A is hot but B shows crowding** (news positive, sentiment late/crowded), the candidate is surfaced *with both stated* — "strong news, but crowded — late entry risk." Never silently drop a name because one feed disagrees; the disagreement is the nuance the user needs.
4. **Catalyst tiebreak:** between two equal-priority candidates, the one with a nearer catalyst (from the calendar) ranks higher.

---

## 8 · Output template
```
🔭 Idea Scout — {DAILY|WEEKLY|FOCUS: theme}
New candidates:
  • {TICKER} ({name}) — why now: {1-line} — fits: {theme} — priority {n}/10  [{feeds agreeing: A/B/C}]
  • {TICKER} … — ⚠️ {disagreement note, e.g. "strong news but crowded"}
Watch (single-feed, not promoted):
  • {TICKER} — {feed} flag only
Promoted to Coverage: {TICKER, TICKER}
```

---

## 9 · Failure & guards
- **on_failure (one feed down):** scan with the remaining feeds, flag the gap in the output ("sentiment feed unavailable — crowding not assessed"); never block the whole scan on one feed.
- **degrade_to:** if all three opinion feeds fail, emit only the mechanical screener (OpenBB / theme radar) candidates with a "signals partial" flag, so the hunt still produces something visible.
- **Cooldown:** **7-day cooldown per name** before the same candidate is re-surfaced or re-promoted to Coverage (the existing proactive-dive rule). A name promoted Monday is not re-promoted until the following week.
- **Dedup + max proactive load:** dedup by ticker within a scan and across the 7-day window; **max 2 new proactive promotions to Coverage per day** (existing guard) so a hot tape can't flood the analyst.
- **Max chain depth:** Idea Scout is hop 1 when it self-triggers (scheduled scan), or **hop 2** when triggered by a Research Librarian uncovered-name signal. Its promotion to Coverage is the next hop. Hard cap **3 hops**: Librarian(1) → Idea Scout(2) → Coverage(3) terminates — Idea Scout must not let that Coverage hand-off chain onward in the same chain. Idea Scout stamps the chain depth on every promotion.

---

## 10 · Module interfaces (for the builder)
```python
# all canonical types from core/objects.py
def run_idea_scout(scope: str = "daily") -> IdeaScoutResult: ...

def feed_news(universe: list[Name])      -> list[Signal]: ...   # A — News Analyst pattern (reference)
def feed_sentiment(universe: list[Name]) -> list[Signal]: ...   # B — Sentiment Analyst pattern (reference)
def feed_theme(universe: list[Name])     -> list[Signal]: ...   # C — native theme radar + momentum
def synthesize_candidates(feeds: list[list[Signal]], covered: list[Name]) -> IdeaScoutResult: ...  # §7

# IdeaScoutResult = {candidates: list[Name], signals: list[Signal], promoted: list[str]}
```
Dependency rule: feeds get data via screener/news/theme adapters; the desk never imports a data SDK directly. Depends inward on objects.

---

## 11 · Edge cases
- **Candidate already in the book** → not a new candidate; route to Coverage as a re-test (or drop if covered same day).
- **Single weak feed only** → "watch," never promoted.
- **User focus area with no matches** → say "no candidates surfaced in {theme}"; do not fabricate names.
- **Crowded late name** (high sentiment, weak structural signal) → surface with the crowding caveat, low priority.
- **Illiquid / non-tradeable / penny name** → flag and deprioritise; do not promote to Coverage.
- **Same name surfacing daily** → cooldown suppresses re-promotion; it stays on "watch" until something changes.

---

## 12 · Definition of done
- [ ] A scheduled scan produces a candidate list matching §8, with feed-agreement counts.
- [ ] A candidate over the ≥2-feed bar routes to Coverage Analyst and creates an initial coverage request.
- [ ] Disagreement (news-hot vs crowded) is shown in the output, not hidden.
- [ ] Already-covered names are filtered out of "new candidates."
- [ ] Cooldown verified (a promoted name is not re-promoted within 7 days).
- [ ] `on_failure` verified (kill one feed → scan continues, gap flagged).
- [ ] Chain depth stamped on every promotion; cap of 3 hops respected.

---

## 13 · Open questions for Louis (decide before/while building)
1. **Candidate object** — keep expressing a candidate as `Name` + `Signal` (recommended — no new canonical object), or formalise a `Candidate` object in §3.1? Default: `Name` + `Signal`.
2. **Promotion bar** — auto-route to Coverage at ≥2 feeds agreeing, or always require your tap before Coverage spends a dive? Default: ≥2 feeds auto-promote, capped at 2/day.
3. **Hunt universe** — how far outside the book do we look: S&P 500, a curated thematic universe, or global? Default: curated thematic universe (the themes already tracked) + S&P 500.
