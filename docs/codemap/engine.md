---
area: engine
title: Engine
summary: What the commands share: analysis cache, reference graph, code-map documents, stamps, navigation, search, locate, changes, syntax
granularity: file
scope:
  - src/topomark/
---

# Engine

> The modules under `src/topomark/` that more than one command needs: the per-file analysis cache,
> the name-based reference graph, the code-map documents and their `check` rules, review stamps,
> and the navigation engine with its search, locate, diff and syntax helpers. Commands
> ([commands.md](commands.md)) parse arguments and render; the engine computes and never prints.
> It reads files through [core.md](core.md)'s `Context` and gets `FileInfo`s from [lang.md](lang.md).
> This scope is the catch-all for `src/topomark/`: a new top-level module lands here unless
> [core.md](core.md) lists it.

## Read these first
- `src/topomark/index.py`: how every analysis is cached, and why a warm run is cheap.
- `src/topomark/workspace.py`: the code-map side (areas, units, stamps, `check`).
- `src/topomark/navigate.py`: the navigation side; most commands start from `Nav`.

## Data flow and entry points
```
Context.code_files -> Index.info/all (lang adapters -> FileInfo, cached per file in the user cache)
Workspace(ctx): areas (docs.load_areas) -> required units -> Graph (fan-in, cross-area edges)
                -> Stamps (stamps.json) -> generated reports -> problems() for check/stale
Nav(ctx) wraps a Workspace: resolve "file#Qual" or "Name", ref_sites, importers (ImportResolver),
                impact_file/impact_symbol, select_tests -> runner_commands, code_map_row, changed_files
search.load(nav)   BM25 index built from Nav.infos, cached with Workspace.derived
locate.*           message word runs or trace frames -> repo files -> enclosing symbols
changes.*          git diff -U0 -> both sides analyzed -> added/removed/signature/body per qualname
syntax.check_file  one file: ast / json / tomllib, or bracket balance on masked text vs HEAD
```
Whole-repo tables (graph tables, identifier counts, import edges, the search index) are stored by
`Index.derived` under a digest of every parsed file's cache key, the config inputs they read and a
fingerprint of the modules that build them (`DERIVED_MODULES`: `graph.py`, `navigate.py`,
`search.py`).

## Files
| file | summary | impact |
|---|---|---|
| `src/topomark/changes.py` | Parse `git diff -U0` (each file from its `diff --git` header: mode-only, binary and empty files too), attribute changed lines to the innermost symbol, classify interface vs body | fan-in 1/1. Run `tests/test_changes.py`; the `changes` JSON is documented in `skills/topomark/reference/commands.md` |
| `src/topomark/docs.py` | Area frontmatter, longest-prefix ownership, units, required and test files, backticked path refs | fan-in 12/0. Ownership or unit rules move every code map: `tests/test_docsystem.py`, `docs/concepts.md` |
| `src/topomark/graph.py` | Name-based reference graph: usable names, fan-in per file, cross-area callers for edge stamps; `Graph.pagerank` (uniform weights) is not what `map` uses (`navigate.pagerank_files`) | fan-in 3/1. Fan-in semantics change the numbers in every area file (FANIN_STALE); run `tests/test_cache.py` and `tests/test_docsystem.py` |
| `src/topomark/index.py` | Per-file analysis cache: 256 marshal shards outside the repo, lazy symbols, `derived` tables keyed by the code that builds them | fan-in 3/1. Changing what is packed: bump `CACHE_FORMAT`; a new module that builds derived tables goes in `DERIVED_MODULES`; run `tests/test_cache.py` and `tools/bench_nav.py` |
| `src/topomark/locate.py` | Message to code by rare word runs (rarity for production places counted among production files, so quoting tests and docs can't hide the source); stack-trace frames to repo files by path suffix (generic `path:line` in linear time, first 500 characters of a line) | fan-in 1/1. Run `tests/test_locate.py`; new trace format: list it in `skills/topomark/reference/commands.md` |
| `src/topomark/navigate.py` | `Nav`, symbol resolution, refs, import edges, impact, test selection, runner commands (POSIX-quoted, `fill_template`), `map`'s PageRank | fan-in 12/3. Behind most commands: run the whole suite; ranking changes go through `tools/eval_nav.py` |
| `src/topomark/search.py` | BM25F index over symbols, files and test methods; deterministic ranking with per-kind weights | fan-in 17/2. Bump `INDEX_VERSION` when the index changes; run `tests/test_search.py` and the eval's search tasks |
| `src/topomark/stamps.py` | `stamps.json`: per-unit surface hashes and git blob ids, per-area edge stamps | fan-in 4/0. Format change: `STAMPS_VERSION` in `src/topomark/contract.py`, migration note in CHANGELOG |
| `src/topomark/syntax.py` | Does a file still parse: Python (this interpreter's grammar; `newer_python` reads `requires-python`), JSON/JSONC, TOML exactly; brace languages by bracket balance | fan-in 2/1. The `post-edit` hook calls `check_file` per edit: keep it index-free; run `tests/test_syntax.py` |
| `src/topomark/workspace.py` | Areas, index, graph, units, stamps and generated reports loaded once; every `check` problem | fan-in 10/0. New problem code: `skills/topomark/reference/code-map.md`; run `tests/test_docsystem.py` |

## Interfaces and cross-area dependencies
- Used by: [commands.md](commands.md) (`Workspace`, `Nav`, `impact_*`, `select_tests`, `search`,
  `locate`, `changes`, `syntax`), `tools/eval_nav.py` and `tools/bench_nav.py` through the CLI.
- Depends on: [lang.md](lang.md) (`registry.analyze`, `FileInfo`, `scan` masking) and
  [core.md](core.md) (`Context`, `Config`, `repo.git`, `contract.estimate_tokens`).

## Change checklist
- Ranking (`search`, `find`, `locate`, `brief`, `tests-for`): run `python3 tools/eval_nav.py` and
  `--compare` against the previous commit; record the numbers in `docs/pilots.md`. Tune weights on
  `tools/eval/tasks.toml`, never the tasks.
- Anything a whole-repo command does per file: `python3 tools/bench_nav.py --runs 3` before and after.
- A new cached table: give `Index.derived` a digest that includes every config key it reads
  (`graph.tables_key`, `search.inputs_key` show how), and list the module that builds it in
  `DERIVED_MODULES` (`src/topomark/index.py`) unless it is there already.
- A `check` rule: problem code, message and fix in `skills/topomark/reference/code-map.md`, test in
  `tests/test_docsystem.py`.

## Invariants and pitfalls
- References are identifier matches on masked text, not resolved bindings: `refs` is a superset and
  fan-in is approximate on purpose (`src/topomark/graph.py` docstring).
- Import edges (`Nav.importers`) never feed fan-in or edge stamps, so adopting a new version does not
  make every code map report `FANIN_STALE` or `EDGES_CHANGED`.
- The cache lives in the user cache directory, keyed by `(mtime_ns, size)`; the engine never writes
  into the repository's files. Only `init`, `draft --write`, `gen`, `sync`, `stamp` and `hook` write,
  and only their own files (`CLAUDE.md`, "Invariants"); `stamps.blob_ids` (`stale`, `diff`, `stamp`)
  adds blob objects to `.git/objects` with `git hash-object -w`.
- Derived tables are only as fresh as their key: a table built by code outside `DERIVED_MODULES`, or
  reading a config key its digest leaves out, is served stale after that code or key changes.
  `graph.partial_names` is packed into each file's cache entry instead: changing it needs a
  `CACHE_FORMAT` bump.
- `syntax.check_file` and the `agent-hook` paths must stay cheap: no `Index`, no reference graph.
- `tests-for` cannot see through modules loaded by computed names (`dynamic_loaders`): CLI-driven
  tests reach this area through `src/topomark/commands/__init__.py`, so a change here often needs
  the whole suite even when `tests-for` picks a few tests.

## Further reading
- `docs/concepts.md`: layers, ownership, units, stamps and fan-in, as users see them.
- `docs/pilots.md`: measured speed and eval numbers, and what changed them.
