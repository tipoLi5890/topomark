# How to write an L1 area file (for people and agents)

Every area file `docs/codemap/<area>.md` follows this skeleton and stays under **260 lines**
(`topomark check` enforces it). This layer joins code and docs: what a file does, whom a change to it
reaches, which tests to run, and which document holds the reasons. **Link, don't restate:** design
reasons already live in the repo's rule files (CLAUDE.md, AGENTS.md, ADRs, architecture docs); here
they get one line and a link.

## Hard rules

- Paths are **full repo-relative paths in backticks**, for example `<dir>/<file>.py`. `check` uses
  them for coverage and dead-path detection.
- **One row per unit.** With `granularity: file` every code file in the area's scope gets its own
  row. With `granularity: dir` the unit is a directory `depth` levels below the scope root, written
  in backticks with a trailing `/`. Assets and data can be covered by one directory row.
- The impact column starts with the fan-in, `fan-in P/T` (P = production files that mention a name
  this unit declares, T = test files), then one sentence on what a change requires: callers to
  check, tests to run, contracts or docs to update. `topomark sync` keeps the numbers current.
- The `area` and `scope` frontmatter decide ownership; change them deliberately. `title` and
  `summary` may be polished; `summary` is one line.
- After writing or updating a row, review-stamp it: `topomark stamp <path>`. New units without a
  stamp and units whose interface changed after review both fail `check`.
- `topomark draft <area>` prints the rows that are missing, summary and fan-in prefilled from the
  code; `topomark draft <area> --write` appends them. Prefilled text is a starting point: read the
  file and correct it before you stamp.

## Skeleton

```markdown
---
area: <do not change>
title: <area name>
summary: <one line: what this area is>
granularity: file
scope:
  - <do not change>
---

# <area name>

> 2 to 4 lines: what this area does, what it does not do, where it sits in the layering (what it
> depends on, what depends on it).

## Read these first
- `<path>`: one line on why a newcomer opens this file first

## Data flow and entry points
5 to 15 lines. Who calls in, the main flow, where the output goes. A small text diagram is fine.

## Files
| file | summary | impact |
|---|---|---|
| `<full/repo/path>` | at most 15 words: what it does, key types | fan-in 12/3. Run `<tests>`; sync `<doc>` |

## Interfaces and cross-area dependencies
- Used by: which areas, through which types (from the cross-area column of _generated/fanin.md)
- Depends on: areas below and external packages

## Change checklist
- Changing A: run …, update … (only what is specific to this area)

## Invariants and pitfalls
- One per line, each linking its source (rule file section, ADR, doc)

## Further reading
- `<doc path>`: one line on what reading it gives you
```
