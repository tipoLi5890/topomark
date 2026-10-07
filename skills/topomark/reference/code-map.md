# The code map: rows, stamps and `check`

## Layout

```
<docs_dir>/README.md        L0: area table, "to change X read Y", highest-impact files, coupling
<docs_dir>/_TEMPLATE.md     how to write an area file
<docs_dir>/<area>.md        L1: one per area, frontmatter + a row per unit
<docs_dir>/stamps.json      review stamps (written only by `topomark stamp`)
<docs_dir>/_generated/      fanin.md and modules.md (written only by `topomark gen`)
```

`docs_dir` defaults to `docs/codemap` (`[topomark] docs_dir` in `topomark.toml`).

## Area frontmatter

```yaml
---
area: core                 # the name commands use
title: Core
summary: routing and storage
granularity: file          # or dir
depth: 1                   # dir only: unit = scope root + N directory levels
scope:
  - src/core/              # directory (trailing /) or one file; longest prefix wins
---
```

## Writing a row

```markdown
| `src/core/router.py` | Routes requests to handlers; `Router`, `make_router` | fan-in 12/3. Run `tests/test_router.py`; update the API doc |
```

- First cell: the full repo path in backticks and nothing else. Directory units end in `/`.
- Summary: what it does and its key types, in at most about 15 words. Not how it works.
- Impact: `fan-in P/T` first, kept current by `topomark sync`, then one sentence on what a change
  requires.
- Link, don't restate: a design reason gets one line and a link to the rule file or ADR.
- `topomark draft <area>` prints missing rows with the summary prefilled from the header comment or
  docstring. Read the file and correct the text before stamping.

## Problem codes from `check`

| Code | Means | Clear it by |
|---|---|---|
| `NOT_LISTED` | a unit has no row in its area file | `topomark draft <area> --write`, correct the row, stamp it |
| `UNOWNED` | no area's scope covers a file | add a scope entry to the right area (or exclude the file in `topomark.toml`) |
| `OWNER_CONFLICT` | two areas claim the same longest prefix | make one scope more specific |
| `DEAD_PATH` | a backticked path in a doc does not exist | fix or remove the path |
| `LINE_CAP` | L0 over `l0_max` or an area over `l1_max` lines | split the area or tighten the prose |
| `FANIN_STALE` | a written `fan-in P/T` is out of date | `topomark sync` |
| `UNIT_COUNT` | a `` `dir/` (N files)`` count is wrong | fix the number |
| `GENERATED_STALE` | `_generated/` is out of date | `topomark gen` |
| `FRONTMATTER` | missing title/summary/scope, bad granularity, empty scope | fix the frontmatter |
| `L0_MISSING`, `L0_LINK` | no L0, or L0 does not link an area file | `topomark init`, or add the link |
| `STAMP_MISSING` | a unit was never reviewed | write its row, `topomark stamp <unit>` |
| `STAMP_CHANGED` | its interface changed since review | `topomark diff <unit>`, update the row, `topomark stamp <unit>` |
| `STAMP_ORPHAN` | a stamp's unit is gone | `topomark stamp --prune` |
| `EDGES_MISSING`, `EDGES_CHANGED` | the area's cross-area callers were never reviewed or changed | review the data-flow and cross-area sections, `topomark stamp --edges <area>` |
| `STAMPS_FORMAT` | stamps.json is from another format version | review, then `topomark stamp --baseline --force` |

## What a stamp covers

A unit's *surface* is its header comment plus its public interface (signatures, constant values, enum
members; for data files the key skeleton). The stamp stores its SHA-256 and the git blob of the
content. Interface changes block `check`; body-only changes show up in `topomark stale` as advisory.
`topomark diff <unit>` shows the interface diff first and the command for the full content diff.
Before committing, `topomark changes` lists the rows whose units had an interface change in the diff,
with their stamp state.

```bash
topomark stale
topomark diff src/core/router.py
topomark stamp src/core/router.py
topomark stamp --edges core
```

Stamp only what you reviewed. `stamp --area` and `stamp --baseline` exist for first adoption and
for deliberate whole-area reviews, not for silencing `check`.
