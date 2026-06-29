# Desk Spec · {DESK NAME}

> Operations manual for one desk. Architecture context: `../BLUEPRINT.md` §2. Status: `../BUILD_LOG.md`.
> Copy this file to `{desk_name}.md` and fill every section. Keep it concrete enough to build from.

## 1 · Identity
Responsibility (1-2 sentences). The one job that makes this desk matter.

## 2 · Triggers
| Trigger | Type (schedule/event/pull) | Scope | Cadence |
|---|---|---|---|

## 3 · Functions operated (from the Spine)
List the Spine functions this desk runs.

## 4 · Inputs & outputs (canonical objects)
Reads: … · Writes: …

## 5 · Core logic
The decision rules / state machine this desk runs. The heart of the spec — be specific.

## 6 · Sources — multi-lens (A / B / C)
Only for opinion desks. For mechanical desks, replace with "single best implementation: {source}, mode {library|vendored}".
- A — {lens} (pattern: {repo}, mode) — role + prompt sketch
- B — …
- C — …

## 7 · Synthesis logic
How the lenses combine. State how disagreement is surfaced (never silently averaged).

## 8 · Output template
```
{written-out template}
```

## 9 · Failure & guards
on_failure: … · degrade_to: … · Guards (cooldown/dedup/depth): …

## 10 · Module interfaces (for the builder)
```python
def run_{desk}(...) -> ...: ...
```
Dependency rule: depends inward on objects, never imports data SDKs directly.

## 11 · Edge cases
…

## 12 · Definition of done
- [ ] …

## 13 · Open questions for Louis
1. …
