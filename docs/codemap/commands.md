---
area: commands
title: Commands
summary: One module per CLI command: arguments, the handler, text and JSON rendering; init's templates
granularity: file
scope:
  - src/topomark/commands/
  - src/topomark/templates/
---

# Commands

> Each module registers one subcommand (`register(sub, common)`) and handles it (`run(args, ctx)`
> returning a `Result`): parse and validate arguments, call the engine ([engine.md](engine.md)),
> render text and the JSON payload. Commands decide what is printed; they compute as little as
> they can themselves. The `init` templates live here too because only `init` writes them.
> Adding a command is the four steps in `CLAUDE.md` ("Adding a command").

## Read these first
- `src/topomark/commands/__init__.py`: `_NAMES` (registry and `--help` order) and `Result`.
- `src/topomark/commands/outline.py`: a small, typical navigation command.
- `src/topomark/commands/agent_hook.py`: the one command that answers in another protocol.

## Data flow and entry points
```
cli.build_parser() -> COMMAND_MODULES() imports topomark.commands.<name> for each of _NAMES
  module.register(sub, common): _common.add(...) a subparser, set_defaults(handler=run)
cli.main -> run(args, ctx): heavy imports here (engine, lang) -> Result(data, text, exit)
navigation:  outline symbol find search locate refs impact brief tests-for syntax changes map
             (read-only on the repo; owner, listed with them in README, reads the code map)
code map:    init draft gen sync stamp     write topomark.toml and docs_dir only (stamp: stamps.json)
             check stale diff owner        write no files
             stale diff stamp              also add the units' blobs to .git/objects (git hash-object -w)
tooling:     hook (.git/hooks/pre-commit)  agent-hook (stdin hook JSON)  doctor  capabilities
```

## Files
| file | summary | impact |
|---|---|---|
| `src/topomark/commands/__init__.py` | Command registry `_NAMES`, `COMMAND_MODULES()` (a name whose module is missing is skipped, and `tests/test_meta.py` fails), the `Result` handlers return | fan-in 26/0. A new command goes in `_NAMES`; `tests/test_meta.py` checks every name registers and is described |
| `src/topomark/commands/_common.py` | `add` (subparser with global flags), `rel` (user path to repo path: from the current directory if it exists there, else repo-relative; outside the repo is NOT_FOUND), `format_problems` | fan-in 2/0. Keep imports light: it loads for `--help` and for every hook call |
| `src/topomark/commands/agent_hook.py` | Claude Code hooks: session-start pointer, pre-read hints once per session, post-edit syntax (quiet about Python when the project requires a newer one); stdin read up to 1 MB | fan-in 0/0. Must exit 0 and stay silent on any error; `hooks/hooks.json` calls it; run `tests/test_agent_hook.py` |
| `src/topomark/commands/brief.py` | Budgeted briefing before an edit: area row, outline, coupled callers, tests, run command | fan-in 0/0. Run `tests/test_brief.py` and the eval's brief tasks |
| `src/topomark/commands/capabilities.py` | Every command, argument and flag from the live parser, plus the exit-code table | fan-in 0/0. Run `tests/test_meta.py` |
| `src/topomark/commands/changes.py` | Diff mapped to symbols: interface vs body, references left, tests, rows to review | fan-in 0/0. Run `tests/test_changes.py` |
| `src/topomark/commands/check.py` | Print `Workspace.problems()`; exit 1 on any | fan-in 0/0. Run `tests/test_docsystem.py`; the pre-commit gate and CI smoke job run it |
| `src/topomark/commands/diff.py` | What changed in a unit since its stamp: surface diff first, then the content diff command | fan-in 0/0. Run `tests/test_docsystem.py` |
| `src/topomark/commands/doctor.py` | Python, git, repo, config, tracked secrets (a warning, never a failure), docs_dir, file counts and the cache directory; exit 1 on a failing check | fan-in 0/0. Covered only by `tests/test_meta.py` (JSON shape) |
| `src/topomark/commands/draft.py` | Rows an area file is missing, summary and fan-in prefilled; `--write` appends them | fan-in 0/0. Appends under `## Files` (or `File table`, `Units`); run `tests/test_init_draft.py` |
| `src/topomark/commands/find.py` | Definitions by name; exact first, code before docs and data, production before tests | fan-in 0/0. Run `tests/test_navigation.py` and the eval's find tasks |
| `src/topomark/commands/gen.py` | Rewrite `<docs_dir>/_generated/` (fan-in table, module graph) | fan-in 0/0. Run `tests/test_docsystem.py` |
| `src/topomark/commands/hook.py` | Install, remove or report the opt-in git pre-commit gate: `check` runs whenever anything is staged, and only its exit 1 blocks the commit (exit 2 to 7 let it through) | fan-in 0/0. Keeps an existing hook as `pre-commit.local`; run `tests/test_docsystem.py` |
| `src/topomark/commands/impact.py` | Render `impact_file` / `impact_symbol`: callers, importers, cross-area users, tests, docs | fan-in 0/0. Run `tests/test_navigation.py` and `tests/test_output_economy.py` |
| `src/topomark/commands/init.py` | Detect stack and manifests, propose areas and excludes, write config and skeleton | fan-in 0/0. `--dry-run` writes nothing (CI checks); run `tests/test_init_draft.py` |
| `src/topomark/commands/locate.py` | Error message or stack trace (file or stdin) to code, via `topomark.locate` | fan-in 0/0. Run `tests/test_locate.py` |
| `src/topomark/commands/map.py` | PageRank-ranked files and key signatures within a token budget | fan-in 0/0. Run `tests/test_navigation.py`; timing in `tools/bench_nav.py` |
| `src/topomark/commands/outline.py` | Declarations with line ranges; several files or a directory at once within a budget | fan-in 0/0. Single-file JSON shape is a contract; run `tests/test_output_economy.py` |
| `src/topomark/commands/owner.py` | Owning area, unit, fan-in and stamp state of a path | fan-in 0/0. Run `tests/test_docsystem.py` |
| `src/topomark/commands/refs.py` | Reference sites grouped production, tests, areas; text capped at 20 | fan-in 0/0. Run `tests/test_navigation.py` and `tests/test_output_economy.py` |
| `src/topomark/commands/search.py` | Keyword search over the BM25 index, capped by `--limit` or `--tokens`, `--area` filter | fan-in 0/0. Run `tests/test_search.py` and the eval's search tasks |
| `src/topomark/commands/stale.py` | Units needing review (exit 1) and body-only changes (advisory) | fan-in 0/0. Run `tests/test_docsystem.py` |
| `src/topomark/commands/stamp.py` | Record reviews: units, `--area`, `--edges`, `--prune`, `--baseline` (refuses over existing stamps; `--baseline --force` overwrites them) | fan-in 0/0. Writes `stamps.json` and the units' blobs into `.git/objects` (`stamps.blob_ids`, `git hash-object -w`, so `diff` can show old content); run `tests/test_docsystem.py` |
| `src/topomark/commands/symbol.py` | One symbol's source, `--signature`, `--skeleton` with bodies elided, `--context`; a bare name declared in several files exits 4 with the candidates, `--skeleton` with `--signature` exits 2 | fan-in 0/0. Run `tests/test_navigation.py` and `tests/test_output_economy.py` |
| `src/topomark/commands/sync.py` | Rewrite stale `fan-in P/T` numbers in area files, nothing else | fan-in 0/0. Run `tests/test_docsystem.py` |
| `src/topomark/commands/syntax.py` | Changed or named files that no longer parse; brackets reported only when HEAD was balanced (new files are not bracket-checked); exit 1 on findings | fan-in 0/0. Run `tests/test_syntax.py` |
| `src/topomark/commands/tests_for.py` | Tests for changed files, through callers up to `--depth`, as runner commands, suite fallback | fan-in 0/0. Run `tests/test_navigation.py` and the eval's tests tasks |
| `src/topomark/templates/__init__.py` | Package marker for the templates `init` renders (`{{name}}` placeholders) | fan-in 0/0 |
| `src/topomark/templates/L0.md` | The L0 index `init` writes: areas table, rule-file links, maintenance commands | fan-in 0/0. Its bash block must parse (`tests/test_meta.py`); run `tests/test_init_draft.py` |
| `src/topomark/templates/_TEMPLATE.md` | How to write an area file: hard rules and the skeleton | fan-in 0/0. Keep in step with `skills/topomark/reference/code-map.md` |
| `src/topomark/templates/area.md` | The skeleton of each area file `init` writes | fan-in 0/0. Its `## Files` heading is where `draft --write` appends; run `tests/test_init_draft.py` |

## Interfaces and cross-area dependencies
- Used by: `src/topomark/cli.py` (parser and dispatch), `hooks/hooks.json` (`agent-hook`), the
  pre-commit script `hook install` writes (`check`).
- Depends on: [engine.md](engine.md) for all analysis, [core.md](core.md) for `Result` plumbing,
  errors and `Context`, [lang.md](lang.md) directly only where a command analyzes an old file
  version (`diff`, `changes`) or picks an adapter (`outline`, `agent-hook`).

## Change checklist
- New command: module with `register` and `run`, name in `_NAMES`, a test with
  `tests.harness.TempRepo`, a row in the README command table and `.github/README.zh-Hant.md`, the
  cheat sheet in `skills/topomark/SKILL.md`, `skills/topomark/reference/commands.md` for navigation
  commands, CHANGELOG `[Unreleased]`, and a row here.
- New flag or JSON field: README table, `skills/topomark/reference/commands.md`, and
  `skills/topomark/reference/json-and-exit-codes.md` when agents read the field.
- Every `topomark ...` line in a bash block of README, `docs/`, `skills/` and the templates must
  parse with the real parser: `python3 -m unittest tests/test_meta.py`.

## Invariants and pitfalls
- Handlers return `Result(data, text, exit)` and never print; errors are `TopomarkError`, never
  `sys.exit` (`CLAUDE.md`, "Invariants").
- Heavy imports go inside `run`: `--help`, `capabilities` and each hook call import every module.
- `--json` is one object with `schema_version` and `command`, also for `agent-hook` (debug only);
  `tests/test_meta.py` runs every command with `--json` to check it.
- Write only what the command owns: `init` (config, `docs_dir`), `draft --write`, `gen`, `sync`,
  `stamp` (`docs_dir`), `hook` (`.git/hooks`); `init --dry-run` writes nothing at all. `stale`,
  `diff` and `stamp` also store blobs in `.git/objects` through `stamps.blob_ids`.
- User-supplied paths go through `_common.rel`: a path outside the repository is NOT_FOUND (exit 4),
  a secret-looking one is REFUSED (exit 2) when it is read.

## Further reading
- `skills/topomark/reference/commands.md`: every navigation command and flag as agents use them.
- `README.md`: the command tables, grouped as agents meet them.
