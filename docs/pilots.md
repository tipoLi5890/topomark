# Pilots (2026-10-05, topomark 0.1.0)

Three of the author's repos, anonymised. All numbers on an Apple-silicon laptop under mixed load; "cold" uses an empty
`TOPOMARK_CACHE`, "warm" the cache from the previous run.

## Pilot A: migration from an in-repo prototype

A Unity game: C# + JS/TS + Python, ~1,000 parseable files. The repository's own prototype (a single Python
script with repo-specific constants) was replaced by topomark plus a `topomark.toml` that reproduces its rules.

- **Parity of the review-stamp surface**, old `surface()` vs topomark adapters over the 413 required files:
  143 identical; the rest were classified line by line.
  - Formatting only: one old line holding several declarations is now one line per declaration;
    statement order.
  - Improvements: members of nested types are now listed; C#/Java constant values keep their real string
    values (the prototype masked them to `""`); `.asmdef` surface includes reference values.
  - By design: non-exported JS/Python functions are not part of the surface; Markdown surface is headings.
  - Regressions found and fixed: C# declarations inside inactive `#else` branches, JS `export default { … }`
    objects, `export default [ … ]` route tables (tests in `tests/test_regressions.py` and `tests/test_lang*.py`).
- **Coverage** was identical (no unit unlisted). Fan-in numbers changed for 7 rows (the new graph counts every
  top-level type, and tests never declare); `topomark sync` updated them.
- Stamps moved to format 2 with `stamp --baseline --force` after the review; `check` and `stale` are clean
  (13 areas, 411 units).
- `tests-for` on a gameplay C# file prints the repository's Unity test command with the test classes it selected
  (6 + 1 test methods).
- Timing: `check` ~1 s warm; first full index ~4 s.

## Pilot B: read-only

Python + TS/TSX, ~2,700 parseable files, ~560k lines. Nothing written (`git status` identical before and after).

| command | time |
|---|---|
| `map --tokens 1500`, cold | 41 s |
| `map --tokens 1500`, warm | 5.5 s |
| `impact` on a backend router, warm | 5.6 s |
| `tests-for` on a backend service, warm | 5.7 s |
| `outline` on a 4,124-line file | 2.6 s |

`init --dry-run` proposes nine areas (seven under the product folder) plus `other`; the repository's existing
rule files (a repo map, nested `CLAUDE.md`) are linked, not duplicated. `tests-for` selected pytest functions
across five test modules.

## Pilot C: read-only

Python + Flutter/Dart, ~600 parseable files. Nothing written. `outline` on Dart works (`main.dart` 1.2 s),
`map --tokens 800` 9.6 s cold. `init --dry-run` proposes four areas plus `other`, one of them the only child
folder of `mobile/`.

## Follow-ups

- Warm runs on ~3k-file repos are ~5.5 s, above the 5 s target: cache the reference graph next to the index.
- `outline` (one file) loads the whole index; it should analyze only the file it prints.
- `init --force` rewrites `topomark.toml` from scratch (hand-written `[[tests.runner]]` tables are lost).
