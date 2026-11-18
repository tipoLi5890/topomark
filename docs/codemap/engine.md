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
- `src/topomark/navigate.py`: the navigation side; most commands start from `Nav`. Test selection,
  runner commands, import resolution, ranking and masking are modules of their own next to it.

## Data flow and entry points
```
Context.code_files -> Index.info/all (lang adapters -> FileInfo, cached per file in the user cache)
Workspace(ctx): areas (docs.load_areas) -> required units -> Graph (fan-in, cross-area edges)
                -> Stamps (stamps.json) -> generated reports -> problems() for check/stale
Nav(ctx) wraps a Workspace: resolve "file#Qual" or "Name", ref_sites, importers (imports.py),
                impact_file/impact_symbol, code_map_row, changed_files
testsel.select_tests(nav, files) -> picks -> runners.runner_commands (quoted shell commands)
ranking.pagerank_files(nav, ...)  map's order;  masking.mask_file  comments and strings blanked
search.load(nav)   BM25 index built from Nav.infos, cached with Workspace.derived
locate.*           message word runs or trace frames -> repo files -> enclosing symbols
changes.*          git diff -U0 -> both sides analyzed -> added/removed/signature/body per qualname
syntax.check_file  one file: ast / json / tomllib, or bracket balance on masked text vs HEAD
```
Whole-repo tables (graph tables, identifier counts, import edges, the search index) are stored by
`Index.derived` under a digest of every parsed file's cache key, the config inputs they read and a
fingerprint of the modules that build them (`DERIVED_MODULES`: `graph.py`, `navigate.py`,
`imports.py`, `masking.py`, `testsel.py`, `search.py`; not `runners.py` or `ranking.py`, which build
no cached table).

## Files
| file | summary | impact |
|---|---|---|
| `src/topomark/changes.py` | Parse `git diff -U0` (each file from its `diff --git` header: mode-only, binary and empty files too), attribute changed lines to the innermost symbol, classify interface vs body | fan-in 1/1. Run `tests/test_changes.py`; the `changes` JSON is documented in `skills/topomark/reference/commands.md` |
| `src/topomark/docs.py` | Area frontmatter, longest-prefix ownership, units, required and test files, backticked path refs | fan-in 13/0. Ownership or unit rules move every code map: `tests/test_docsystem.py`, `docs/concepts.md` |
| `src/topomark/graph.py` | Name-based reference graph: usable names, fan-in per file (Python to Python also needs an import), cross-area callers for edge stamps (`map`'s ranking is `ranking.pagerank_files`) | fan-in 4/1. Fan-in semantics change the numbers in every area file (FANIN_STALE); run `tests/test_cache.py` and `tests/test_docsystem.py` |
| `src/topomark/index.py` | Per-file analysis cache: 256 marshal shards outside the repo (`cache_base`: `TOPOMARK_CACHE`, `XDG_CACHE_HOME`, `%LOCALAPPDATA%` on Windows, `~/.cache`), lazy symbols, a cold whole-repo parse of `PARALLEL_MIN` or more files in worker processes (`TOPOMARK_JOBS`; in this process when workers cannot start), `derived` tables keyed by the code that builds them; a save merges into the shard on disk (runs at once keep each other's entries); indexes and repository folders unused for `KEEP_DAYS` / `KEEP_REPO_DAYS` are swept | fan-in 3/1. Changing what is packed: bump `CACHE_FORMAT`; a new module that builds derived tables goes in `DERIVED_MODULES`; run `tests/test_cache.py` and `tools/bench_nav.py` |
| `src/topomark/locate.py` | Message to code by rare word runs (rarity for production places counted among production files, so quoting tests and docs can't hide the source); stack-trace frames to repo files by path suffix (generic `path:line` in linear time, first 500 characters of a line) | fan-in 1/1. Run `tests/test_locate.py`; new trace format: list it in `skills/topomark/reference/commands.md` |
| `src/topomark/imports.py` | `ImportResolver`: import specifiers to repo files. Python and JS/TS (relative and absolute modules, `src/` layouts, aliases, `index` files), C-family quoted includes, Dart, Go packages (the module prefix is learned from the repository's own imports: `learn_go`), Rust `mod` and `crate::`/`super::`/`self::` paths, Java and Kotlin; `resolve_imports`, `reverse_edges` | fan-in 2/1. Builds a cached table (`DERIVED_MODULES`); run `tests/test_navigation.py` (`ImportEdgeTests`, `OtherLanguageImportTests`). A new language: its adapter's `imports_of` says what was written (`src/topomark/lang/_imports.py`), this file what it resolves to |
| `src/topomark/masking.py` | `mask_file` (comments and strings blanked with the file's adapter syntax), `word_rx`, `NON_CODE_LANGS`; a leaf that needs only `lang/` | fan-in 4/1. `syntax.check_file` and the post-edit hook import it: keep it free of the index and the workspace |
| `src/topomark/navigate.py` | `Nav`, symbol resolution, refs, importers, doc mentions (docs read once per run), impact summaries, code-map row, changed files (a caller that already checked the revision says so), skeleton gaps | fan-in 11/1. Behind most commands: run the whole suite |
| `src/topomark/ranking.py` | `map`'s personalised PageRank over the reference graph (a focus file's users share `USERS_SHARE` of its weight) and the per-symbol weights | fan-in 1/0. Run `tests/test_navigation.py` (`MapTests`) and `tools/bench_nav.py` |
| `src/topomark/runners.py` | `[[tests.runner]]` templates filled with the picked tests, every value quoted for a POSIX shell (`fill_template`, `runner_commands`) | fan-in 3/1. Quoting is a safety boundary: `tests/test_safety.py` |
| `src/topomark/search.py` | BM25F index over symbols, files and test methods; deterministic ranking with per-kind weights (a test weighs less than the share it lends to the code it uses) | fan-in 2/0. Bump `INDEX_VERSION` when the index changes; run `tests/test_search.py` and the eval's search tasks |
| `src/topomark/stamps.py` | `stamps.json`: per-unit surface hashes and git blob ids (`blob_ids`, `blob_text`), per-area edge stamps; a file that is not JSON (conflict markers) is a CONFIG error | fan-in 3/0. Format change: `STAMPS_VERSION` in `src/topomark/contract.py`, migration note in CHANGELOG |
| `src/topomark/testsel.py` | `select_tests`: tests that mention a changed file's names, then callers up to `--depth` hops by import edges and name references; `pick_tests`, `test_methods`, `TestPick` | fan-in 5/0. Ranking changes go through `tools/eval_nav.py` (tests tasks); `search` reads `test_methods` for its cached index (`DERIVED_MODULES`) |
| `src/topomark/syntax.py` | Does a file still parse: Python (this interpreter's grammar; `newer_python` reads `requires-python`), JSON/JSONC, TOML exactly; brace languages by bracket balance | fan-in 2/1. The `post-edit` hook calls `check_file` per edit: keep it index-free; run `tests/test_syntax.py` |
| `src/topomark/workspace.py` | Areas, index, graph, units, stamps and generated reports loaded once; every `check` problem (directories and every area's edges each from one pass); `current_blobs` (ids computed, never stored); `interface_changed` (a stamp whose hash differs is settled by re-reading the reviewed blobs with today's adapters) and `stamp_state` (`none`, `current`, `changed`: what `owner`, `impact`, `brief` and `changes` report, so they agree with `check`) | fan-in 10/0. New problem code: `skills/topomark/reference/code-map.md`; run `tests/test_docsystem.py` |

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
- Between two Python files, fan-in also needs an import: the referrer imports the declaring module,
  or a module that imports it and mentions the name (`graph.build_tables`). Every other
  pair of languages, and a file that loads modules by computed names, is judged by name alone:
  JS/TS package aliases and C# namespaces cannot be resolved from the repository.
- Changing what counts as a reference changes fan-in numbers and cross-area callers in every
  adopted code map (`FANIN_STALE`, `EDGES_CHANGED`): say so in CHANGELOG with the commands to run.
- The cache lives in the user cache directory, keyed by `(mtime_ns, size)`; the engine never writes
  into the repository's files. Only `init`, `draft --write`, `gen`, `sync`, `stamp` and `hook` write,
  and only their own files (`CLAUDE.md`, "Invariants"); `stamps.blob_ids` (`diff`, `stamp`)
  adds blob objects to `.git/objects` with `git hash-object -w`.
- Derived tables are only as fresh as their key: a table built by code outside `DERIVED_MODULES`, or
  reading a config key its digest leaves out, is served stale after that code or key changes.
  `graph.partial_names` is packed into each file's cache entry instead: changing it needs a
  `CACHE_FORMAT` bump.
- `syntax.check_file` and the `agent-hook` paths must stay cheap: no `Index`, no reference graph.
- CLI-driven tests reach this area several imports away (harness, `cli.main`, the command registry,
  a handler's own import), past `tests-for`'s default `--depth 2`: a change here often needs the
  whole suite even when `tests-for` picks a few tests.

## Further reading
- `docs/concepts.md`: layers, ownership, units, stamps and fan-in, as users see them.
- `docs/pilots.md`: measured speed and eval numbers, and what changed them.
