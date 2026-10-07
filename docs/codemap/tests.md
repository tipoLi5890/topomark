---
area: tests
title: Tests
summary: The unittest suite: CLI-driven tests in throwaway git repos, adapter tests over fixtures, repo-wide meta checks
granularity: file
scope:
  - tests/
---

# Tests

> Standard-library `unittest`, no pytest. Most tests run the real CLI in process
> (`tests.harness.run_cli`) against a throwaway git repo (`TempRepo`) with its own cache directory;
> the adapter tests read the fixtures under `tests/fixtures/` (excluded from this map); `test_meta`
> checks repository-wide contracts. The whole suite: `python3 -m unittest discover -s tests -t .`.

## Read these first
- `tests/harness.py`: `run_cli`, `json_of` and `TempRepo`, used by nearly every test.
- `tests/test_meta.py`: the contracts that fail when a command, a doc or an `open()` drifts.

## Data flow and entry points
```
tests/harness.py: sets TOPOMARK_CACHE to a fresh temp dir (always), puts src/ on sys.path
  TempRepo({path: text}) -> git init + commit -> repo.cli(...) / repo.json(...) -> cli.main in process
test_lang.py: tests/fixtures/lang/<lang>/ -> registry.analyze -> GOLDEN outlines, surfaces
test_lang_scan.py: inline snippets -> scan.mask / simple.mask_shell / preprocessor helpers directly
test_meta.py: every registered command with --json; AST scan of src/ for text I/O; docs' bash lines;
  init templates exist; the docs/config.md example parses as a config
```
`tests-for` runs these by file (`[[tests.runner]]` in `topomark.toml`); because commands are loaded by
computed names, a change deep in the engine often needs the whole suite.

## Files
| file | summary | impact |
|---|---|---|
| `tests/__init__.py` | Package marker so `-t .` discovery imports `tests.harness` | fan-in 0/0 |
| `tests/harness.py` | `run_cli` in process, `json_of`, `TempRepo` throwaway git repos, per-run cache (always a fresh temp dir, even when `TOPOMARK_CACHE` is exported) | fan-in 0/0. Every CLI test depends on it: run the whole suite after a change |
| `tests/test_agent_hook.py` | Hook payloads on stdin: formats, once-per-session hints, silence on errors, oversized payloads and newer-Python code, a light CLI import, hooks.json | fan-in 0/0 |
| `tests/test_brief.py` | `brief` for files and names: area row, coupled callers, tests, budget trimming | fan-in 0/0 |
| `tests/test_cache.py` | Cache entries match fresh analysis; one-shard reads; digests follow edits and engine code; the harness's own cache; glob matcher | fan-in 0/0 |
| `tests/test_changes.py` | `changes`: interface vs body, references left, tests and rows to review, rev modes; diff parsing (spaces, mode, binary) | fan-in 0/0 |
| `tests/test_docsystem.py` | Code map end to end: coverage, dead paths, caps, fan-in sync, stamps, dir units, hook | fan-in 0/0 |
| `tests/test_init_draft.py` | `init` plan, dry run, write, refuse, force; `draft` rows and `--write` | fan-in 0/0 |
| `tests/test_lang.py` | Adapter `GOLDEN` outlines per fixture, signatures, docs, surfaces, fan-in types | fan-in 0/0. Regenerate a golden only after reading the new outline |
| `tests/test_lang_scan.py` | Masking scanner on literals that trip naive scanners (inline snippets, maskers called directly); offsets preserved | fan-in 0/0 |
| `tests/test_locate.py` | `locate`: messages with interpolated values, sources that tests quote verbatim, `--regex`, each trace format, long lines in linear time | fan-in 0/0 |
| `tests/test_meta.py` | Registry and `capabilities`, JSON envelope for every command, text I/O, docs parse, zh-Hant dashes, templates exist, `docs/config.md` example is a valid config | fan-in 0/0. Fails on any undocumented or unparseable command line in the docs |
| `tests/test_navigation.py` | outline, symbol, find, refs, impact, tests-for (test support code, odd paths), map end to end; import edges; recall | fan-in 0/0 |
| `tests/test_output_economy.py` | `symbol --skeleton`, multi-file `outline`, capped `refs` and `impact` text | fan-in 0/0 |
| `tests/test_regressions.py` | Adapter regressions found by the prototype parity run | fan-in 0/0 |
| `tests/test_safety.py` | Never read or run: secrets behind links or too large to parse, paths outside the repo, unquoted runner paths | fan-in 0/0 |
| `tests/test_search.py` | `search` ranking, test evidence, code-map rows, limits and `--area`, odd whitespace in names | fan-in 0/0 |
| `tests/test_syntax.py` | `syntax`: Python (interpreter and `requires-python` in the message), JSON(C), TOML errors; bracket checks vs HEAD; Swift raw strings; `check_file` index-free | fan-in 0/0 |
| `tests/test_tools.py` | The `tools/` scripts end to end on tiny inputs: the eval (errors, controls, `--compare` with a rejected config key), no stale gold in the real tasks, a deterministic synthetic repo that runs no user hook, the bench's hook checks | fan-in 0/0 |

## Interfaces and cross-area dependencies
- Used by: CI (`.github/workflows/ci.yml`: Ubuntu 3.11 and 3.14, Windows 3.12), `tests-for`.
- Depends on: [core.md](core.md) (`cli.main`), and through the CLI on every other area.

## Change checklist
- New behaviour: a test with `TempRepo` (`CLAUDE.md`, "Adding a command").
- New fixture under `tests/fixtures/`: it is excluded from this map and from ruff; give it a `GOLDEN`
  entry in `tests/test_lang.py`.
- Tests that start a subprocess use `sys.executable -m topomark` with `PYTHONPATH`, not
  `bin/topomark`: the suite also runs on Windows.

## Invariants and pitfalls
- Never touch the user's cache: `tests/harness.py` points `TOPOMARK_CACHE` at a fresh temp dir,
  even when the developer's shell exports one (`tests/test_cache.py` checks it).
- A test that reaches stdin must patch `sys.stdin` (`agent-hook` reads it).
- `tests/test_meta.py` runs every command with `--json` in a `TempRepo`, filling each required
  positional with `x`: a command that needs a real value gets a case there, as `hook` and `init` do.

## Further reading
- `CONTRIBUTING.md`: the checklist before a pull request.
