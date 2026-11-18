# Pilots and measurements

"Current numbers" is what the code does today. Everything under "History" is a dated log, kept as it was
written: later sections supersede earlier ones.

## Current numbers

### Navigation eval on the pinned snapshot (2026-11-17)

`python3 tools/eval_nav.py`: 42 tasks, 28 about this repository as it was at `v0.2.0` (`snapshot` in
`tools/eval/tasks.toml`, exported without `tools/eval/`), 14 on a generated 150-file repo. One task is a control
(`expect = "miss"`), so 41 are scored. CI fails under an MRR of 0.75 (`--fail-under`).

| kind | scored | hit@1 | hit@5 | MRR | mean output tokens |
|---|---:|---|---|---:|---:|
| find | 9 | 5 | 9 | 0.722 | 146 |
| search | 7 | 4 | 6 | 0.702 | 516 |
| locate | 8 | 8 | 8 | 1.000 | 166 |
| brief | 4 | 3 | 3 | 0.786 | 467 |
| tests-for | 5 | 3 | 5 | 0.740 | 143 |
| refs | 3 | 3 | 3 | 1.000 | 137 |
| impact | 3 | 3 | 3 | 1.000 | 71 |
| map | 2 | 1 | 2 | 0.750 | 1142 |
| all | 41 | 30 | 39 | 0.823 | 283 |

Twelve tasks were added on 2026-11-17: the kinds `refs`, `impact` and `map`, which the eval did not score, and
Go, C# and TypeScript questions on the synthetic repo (the 30 older tasks were Python and one TypeScript chain).
They were written from what the code is before any was run. With them and no change to the commands the MRR was
0.789; one gold was then widened (`refs owner_of` named one of six equally right callers and now accepts any),
which is in that number.

Two ranking changes followed, each from a miss the new and old tasks showed:

- `find` orders partial matches of the same standing by how much of the name the query covers, where it used
  the path. `find stamp` went from rank 2 to 1 (`Stamps` before `STAMPS_VERSION`) and `find runner` from 4 to 3;
  `find frontmatter` went from 2 to 3 (`FrontmatterError` in `tools/` now precedes `parse_frontmatter`).
- `map --focus` on a file that uses nothing listed that file alone, so the file that calls it was missing
  (`synth-map-focus-leaf`: no rank, now rank 1). The users of a focus file now share half its weight.

Together: 0.789 to 0.823. The 29 tasks scored on 2026-10-09 read 0.753 then and 0.768 now.

Known misses: `search` puts the `check` problem list sixth and the runner placeholders fourth; `brief` on
`config.py` lists the gold test seventh, after the five callers (`related` lists callers before tests, so a test
cannot lead while there are callers); `find runner` is third of four functions with "runner" in their name;
`map` on the synthetic repo puts a hub second, not first.

Why the eval moved to a snapshot. Until 0.2.0 the 27 tasks ran on the checkout, so the text being searched
changed with every commit while the golds stayed. By 2026-10-09 the same tasks read MRR 0.687 (locate 5/6,
search hit@5 4/6) against the 0.730 recorded on 2026-10-06, and `--compare` against five earlier commits gave
the same ranks on both sides: the ranking code had not changed, the repository had. Two golds had gone stale
without the check noticing, because the symbol they named still existed: the secret-file refusal moved from
`repo.py#read_text` into `repo.py#safe_path` and `index.py#Index.info`, so `locate` answered correctly and
was scored a miss. The gold check now also requires a `locate` gold to contain the message. The task file
itself was among `locate`'s answers (as a doc hit); the snapshot leaves `tools/eval/` out.

What these numbers do not show: the tasks were written by topomark's author about topomark's own code, 4 to 8
per kind, so one task is 12 to 25 points of hit@1 in its kind. They catch a ranking regression; they are not
evidence of how the commands do on other repositories.

### Speed (2026-10-09)

`python3 tools/bench_nav.py --runs 3` on the 3,000-file synthetic repo (2026-10-09, an idle Apple-silicon laptop, warm
cache, a fresh process per run): CPU time of 0.2.0 and of the code after the first run of changes following it
(pinned eval, config warnings, the incomplete-outline flag, the `navigate.py` split, fan-in by import).

| case | 0.2.0 | after |
|---|---:|---:|
| `map` | 0.22 s | 0.22 s |
| `impact-file` | 0.16 s | 0.16 s |
| `impact-symbol` | 0.25 s | 0.25 s |
| `tests-for` | 0.16 s | 0.16 s |
| `outline-big` | 0.06 s | 0.05 s |
| `outline-small` | 0.06 s | 0.05 s |
| `symbol` | 0.06 s | 0.05 s |
| `search` | 0.17 s | 0.16 s |
| `brief-file` | 0.17 s | 0.17 s |
| `brief-symbol` | 0.28 s | 0.28 s |
| `hook-session` | 0.05 s | 0.05 s |
| `hook-pre-read` | 0.06 s | 0.06 s |
| `hook-post-edit` | 0.07 s | 0.06 s |
| `hook-post-edit-broken` | 0.10 s | 0.09 s |
| `map`, cold cache | 2.11 s | 2.17 s |

Nothing got slower. These are several times lower than the 2026-10-06 tables under "History", which were
measured at a load average of 20 to 40: compare within a table, never across them. The work after 0.3.0
(CHANGELOG.md, `[Unreleased]`) was timed against 0.3.0 on the same repo on 2026-11-17: a cold `map` 2.7 s in
one process and 1.0 s with worker processes, the warm commands within noise of 0.3.0.

One thing did get much faster, on real code rather than the synthetic repo: the C-family adapter took seconds
per file (and sometimes never returned) on declarations with long identifiers, an exponential pattern that
the synthetic C-free repo could not show. 14,000 installed JS, TS and C-family files that took minutes parse
in 15 seconds. The test suite takes about 18 s on the same laptop (25 s before the harness stopped starting
five git processes per throwaway repo), with 218 tests instead of 194 (both on 2026-10-09).

# History

## Pilots (2026-10-05, topomark 0.1.0)

Three of the author's repos, anonymised. All numbers on an Apple-silicon laptop under mixed load; "cold" uses an empty
`TOPOMARK_CACHE`, "warm" the cache from the previous run.

### Pilot A: migration from an in-repo prototype

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

### Pilot B: read-only

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

### Pilot C: read-only

Python + Flutter/Dart, ~600 parseable files. Nothing written. `outline` on Dart works (`main.dart` 1.2 s),
`map --tokens 800` 9.6 s cold. `init --dry-run` proposes four areas plus `other`, one of them the only child
folder of `mobile/`.

### Follow-ups

- Warm runs on ~3k-file repos are ~5.5 s, above the 5 s target: cache the reference graph next to the index.
  Done; see "Performance on a 3,000-file synthetic repo" below.
- `outline` (one file) loads the whole index; it should analyze only the file it prints. Done: it reads one
  cache shard.
- `init --force` rewrites `topomark.toml` from scratch (hand-written `[[tests.runner]]` tables are lost).
  Done: `--force` never replaces an existing `topomark.toml`.

## Performance on a 3,000-file synthetic repo (2026-10-06)

`tools/synth_repo.py` generates the repo (3,000 files, ~500k lines: Python 45 %, TS/TSX 40 %, JS, Go and C# 5 %
each, Markdown docs, a test file for one module in four); `tools/bench_nav.py --runs 3` times each command as a
fresh `python3 -m topomark` process on a warm cache. The laptop was heavily loaded, so wall time was several times
the CPU time; CPU time (user + system) is the stable number. "Before" is 0.1.0 plus import edges,
"after" is the cache and ranking work below; the two ran back to back.

| command | CPU before | CPU after | wall before | wall after |
|---|---:|---:|---:|---:|
| `map --tokens 1500` | 1.31 s | 0.77 s | 6.7 s | 3.6 s |
| `impact py/core/hub.py` | 1.17 s | 0.56 s | 7.0 s | 2.6 s |
| `impact CoreHub` | 1.27 s | 0.90 s | 6.3 s | 4.2 s |
| `tests-for py/chain/leaf.py` | 1.16 s | 0.53 s | 7.0 s | 1.7 s |
| `outline` (3,600-line file) | 0.43 s | 0.20 s | 3.1 s | 0.7 s |
| `outline` (5-line file) | 0.40 s | 0.20 s | 2.2 s | 0.7 s |
| `symbol file#Name` | 0.38 s | 0.18 s | 1.9 s | 0.7 s |
| `map`, cold cache | 8.6 s | 7.2 s | 32 s | 25 s |

A single-file `outline` costs the same on the 80-file and the 3,000-file synthetic repo (0.21 s CPU, of which
~0.16 s is interpreter start-up). The warm `map`/`impact` target of 5 s holds even on the loaded machine.

What changed, in the order the profile ranked it:

- Exclude, secret and test-pattern lists compile into one matcher each (it ran 37 globs per file): 2.0 s → 0.2 s
  of wall time for the file list.
- The analysis cache went from one 17.6 MB JSON file to 256 `marshal` shards keyed by a hash of the path, and a
  cached file decodes its symbols and identifiers on first use. Single-file commands read one shard; a save
  rewrites only the shards that changed. Cache format 2; caches of older formats are deleted.
- The reference graph's tables, the identifier counts and the import edges are cached under a digest of every
  parsed file's `(path, mtime, size)` and the config keys they depend on (`min_name`, `keep_short_names`, test
  patterns), so `check`, `sync` and fan-in are computed exactly as before.
- `map`'s PageRank runs on integer-indexed lists with the same arithmetic, and `map` stops building symbols
  once no remaining file can reach the token budget (an exact bound).

The JSON of `map`, `impact`, `tests-for`, `find`, `refs`, `outline`, `symbol` and `init --dry-run` was compared
before and after on a frozen copy of this repo and on the synthetic repo: identical.

## Final state on the 3,000-file synthetic repo (2026-10-06)

Every navigation command and the plugin hooks, on the final code, with `tools/bench_nav.py --runs 5` on the same
synthetic repo (warm cache, a fresh `python3 -m topomark` process per run; the `hook-*` cases send the hook
payload on stdin with a new session each run, so `pre-read` always takes its first-read path and prints its
hints). The laptop's load average was 20 to 40 throughout, so wall time is two to five times the CPU time and
moves by a factor of two between runs; the CPU column is the number to compare.

| command | CPU | wall median |
|---|---:|---:|
| `map --tokens 1500` | 0.89 s | 3.9 s |
| `impact py/core/hub.py` | 0.67 s | 2.2 s |
| `impact CoreHub` | 1.04 s | 4.4 s |
| `tests-for py/chain/leaf.py` | 0.63 s | 2.7 s |
| `outline` (3,600-line file) | 0.22 s | 0.9 s |
| `outline` (5-line file) | 0.23 s | 0.9 s |
| `symbol file#Name` | 0.24 s | 0.9 s |
| `search invoice payment service` | 0.68 s | 4.1 s |
| `brief py/core/hub.py` | 0.71 s | 4.3 s |
| `brief CoreHub` | 1.12 s | 5.7 s |
| `agent-hook session-start` (no code map) | 0.18 s | 0.45 s |
| `agent-hook pre-read` (3,600-line file, hints printed) | 0.20 s | 1.1 s |
| `agent-hook post-edit` (3,600-line file parses) | 0.25 s | 1.3 s |
| `map`, cold cache | 8.3 s | 37 s |

No warm command uses more than 1.2 s of CPU. On wall time, everything but `brief CoreHub` stayed under 5 s in
this run; `brief` on a name does `impact`'s reference scan plus test selection, and at a load average near 30
its median was 5.7 s. Two back-to-back rounds of the bench as of the perf change against the final code gave
the same CPU within run-to-run noise (`map` 0.94/0.86 s before, 0.77/1.04 s after; `impact` on a file
0.59/0.66 s before, 0.58/0.74 s after), so the commands added since did not slow the old ones down.

The hooks cost about 0.2 s of CPU per call. Most of it is fixed: a ranged read, which `pre-read` drops before
touching git or the file, still costs 0.14 s (the launcher's Python version probe, the interpreter, topomark's
imports and the parser). A separate run on a copy of the synthetic repo with a code map (`init`, six areas)
measured the cases the bench does not cover, CPU medians of seven runs: `session-start` listing the areas 0.17 s, `pre-read` of a small
file in a new area 0.20 s, a repeated `pre-read` that stays silent 0.21 s, a ranged read (`offset`/`limit`)
0.14 s, `post-edit` that reports a syntax error 0.27 s. All far inside the hooks' 5-second timeout.

## Navigation eval (2026-10-06, on the checkout of that day)

`tools/eval_nav.py`: 30 tasks (27 on this repo, 3 on a generated 150-file repo), written before `search`,
`locate` and `brief` existed; since then only one gold changed, because the code it named moved
(`commands/impact.py#_symbol` → `navigate.py#impact_symbol`). Baseline is the commit that added the eval,
when the 16 tasks for the missing commands and one for a missing flag were skipped; "final" is the
code after the hooks, before this repo got its own code map.

| kind | tasks run | hit@1 | hit@5 | MRR | mean output tokens |
|---|---:|---|---|---:|---:|
| find, baseline | 8 | 2 | 8 | 0.494 | 122 |
| find, final | 8 | 2 | 8 | 0.552 | 137 |
| tests-for, baseline | 5 | 1 | 1 | 0.200 | 37 |
| tests-for, final | 6 | 3 | 5 | 0.639 | 103 |
| search, final | 6 | 3 | 6 | 0.658 | 491 |
| locate, final | 6 | 6 | 6 | 1.000 | 196 |
| brief, final | 4 | 3 | 3 | 0.786 | 317 |
| all, final | 30 | 17 | 28 | 0.711 | 237 |

`find stamp` moved from rank 5 to 2 and `find frontmatter` from 3 to 2 (code before docs); `find runner` slid
from 3 to 4 when `runner_commands` was added for `brief`, a fourth function with "runner" in its name. The
synthetic import chains (`py/chain/leaf.py` and `ts/chain/leaf.ts`, two hops from their tests) are found at the
default `--depth 2` and missed at `--depth 1`, which is why the default is 2. `locate` put the right symbol first
for every message and the Python trace. `search` found every gold in its top five, three of them first; the
misses at rank 1 were the secret-file refusal (rank 4), the runner placeholders (2) and the `check` problem
list (5). `brief` put the gold first in three of four tasks; for `config.py` the gold test (`test_meta.py`,
which feeds `docs/config.md` through `Config.from_dict`) came seventh, because `brief` lists the five callers
before the tests. `tests-for` now names more tests, so its output grew from 37 to 103 tokens on average.

`tests-for src/topomark/navigate.py` hits only because tests that import `navigate` directly were added on this
branch: the CLI-driven tests reach it through `commands/__init__.py`, which loads command modules by computed
names, so `tests-for` reports that file under `dynamic_loaders`.

## Dogfood: topomark's own code map (2026-10-06)

`init` proposed three areas (`src`, `tests`, `tools`); the map uses seven, split by frontmatter scope:
core (launcher, CLI, context, config, errors, contract, repo), commands (with `init`'s templates), engine
(everything else under `src/topomark/`), lang, plugin (skill, hooks, Claude manifests), tools and tests.
`tests/fixtures/**` is excluded, and `every_file_roots` gives the launcher, the hooks, the skill, the
manifests and the templates rows of their own: 92 units, `check` green, and `bin/topomark check` runs in
CI's smoke job.

What it turned up:

- The runner example in the README and `docs/config.md` (`python3 -m unittest {names}`, `names = "class"`)
  printed bare class names, which unittest cannot resolve (`python3 -m unittest ImportEdgeTests` fails).
  Both now use `names = "file"`; unittest accepts test file paths.
- `src/topomark/search.py` shows fan-in 16/1, 15 of them from its `search` function sharing a name with
  `re.search`. Fan-in is approximate by design; the L0 page says so next to the number.
- `tests-for src/topomark/navigate.py` prints `python3 -m unittest tests/test_navigation.py` (27 tests,
  green), the one test file that imports it directly. Most tests reach `navigate` through the CLI's
  computed imports, which a static search cannot follow; for a command module no test names, such as
  `doctor.py`, `tests-for` says "may miss tests" and prints the suite.
- The eval moved a little once the map existed (code-map rows feed `search`, and the fixtures left the
  file list): `find secret` went from rank 3 to 1; of the search tasks, the secret-file refusal went from
  4 to 3, the runner placeholders from 2 to 3 and the `check` problem list from 5 to 6 (search hit@5 6 → 5,
  MRR 0.658 → 0.639; all tasks MRR 0.711 → 0.730). The weights were left alone.
- The generated fan-in report was titled "C# / code fan-in", a leftover from the prototype; it is
  now "Fan-in" (run `topomark gen` once after upgrading).
