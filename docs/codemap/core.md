---
area: core
title: Core: CLI, context, config, repo
summary: Entry point, argument parsing, the JSON and exit-code contract, config, git file list, secrets
granularity: file
scope:
  - bin/
  - src/topomark/__init__.py
  - src/topomark/__main__.py
  - src/topomark/cli.py
  - src/topomark/context.py
  - src/topomark/config.py
  - src/topomark/errors.py
  - src/topomark/contract.py
  - src/topomark/repo.py
---

# Core: CLI, context, config, repo

> How a `topomark` invocation starts and what every command can rely on: the launcher, the parser and
> its output contract (`--json` envelope, exit codes, `TopomarkError`), the per-run `Context`, the
> `topomark.toml` loader, and the repository as git lists it, with secrets never read. No analysis
> here: parsing lives in [lang.md](lang.md), the shared engine in [engine.md](engine.md), each
> command in [commands.md](commands.md). The invariants are in `CLAUDE.md`; this file only points.

## Read these first
- `src/topomark/cli.py`: the dispatch and the output contract every command goes through.
- `src/topomark/context.py`: what a handler gets; everything on it is lazy.
- `src/topomark/repo.py`: where file lists, globs and the secret rule come from.

## Data flow and entry points
```
bin/topomark (finds Python >= 3.11, PYTHONPATH=src)  or  python -m topomark  or  the pipx entry point
  -> __main__.py -> cli.main(argv)
       build_parser(): global flags + one subparser per module in commands.COMMAND_MODULES()
       args.handler(args, Context(args)) -> Result(data, text, exit)
       --json: {"schema_version", "command", **data} on stdout; else text on stdout
       TopomarkError -> error envelope (--json) or "error: CODE: message" on stderr, exit by code
       any other exception -> INTERNAL (exit 7), traceback with --debug
Context: root (git rev-parse) -> config (topomark.toml) -> all_files (git ls-files) -> files -> code_files
```
`Context` builds nothing until a command asks, so `doctor`, `capabilities` and `agent-hook` work in a
repo whose config is broken, and `--help` stays fast (heavy imports sit inside each `run`).

## Files
| file | summary | impact |
|---|---|---|
| `bin/topomark` | Bash launcher: picks python3.14 down to python3 if >= 3.11 (each one is started to ask: a version manager's shim exists for versions that are not active), sets PYTHONPATH, runs the CLI with `python -P` (the working directory, an untrusted repo, never on `sys.path`) | fan-in 0/0. The plugin hooks and the README install run it; keep it LF and executable (CI checks); keep `-P`: `tests/test_safety.py` |
| `src/topomark/__init__.py` | `__version__` from the checkout's pyproject.toml, else installed metadata (imported lazily) | fan-in 0/0. Version bumps go through pyproject.toml and `tools/sync_version.py`, never here |
| `src/topomark/__main__.py` | `python -m topomark` calls `cli.main()` | fan-in 0/0 |
| `src/topomark/cli.py` | Parser from the command registry: only the command given (`_command_in`, `build_parser(only)`), all of them for help, no command or a word that is not one; global flags anywhere, JSON and error envelopes (also for `--json` with no command), exit mapping, a quiet end when the reader closes the pipe | fan-in 2/3. Envelope or exit changes: `tests/test_meta.py` (also: one command parses like the whole parser), README exit table, `skills/topomark/reference/json-and-exit-codes.md` |
| `src/topomark/config.py` | `Config` and `TestRunner` from topomark.toml; unknown sections and keys become `Config.warnings` (`Context.config` prints them on stderr); a wrong type, the removed `lang` and a `docs_dir` outside the repository are CONFIG errors | fan-in 6/1. New key: `_ALLOWED`, `docs/config.md` (its example is parsed by `tests/test_meta.py`) |
| `src/topomark/context.py` | Lazy per-run `Context`: root, config, git files, excludes, parseable files, `read`, `log` | fan-in 31/2. Every command uses it; keep each property lazy |
| `src/topomark/contract.py` | Versioned contracts: schema version, stamps format, config file name, `estimate_tokens` | fan-in 6/1. A `SCHEMA_VERSION` or `STAMPS_VERSION` bump is a CHANGELOG entry and a migration note |
| `src/topomark/errors.py` | Exit-code table, error codes, remediation text, the one `TopomarkError` | fan-in 26/1. New code or exit: README and skill exit tables, `capabilities` reads `EXIT` |
| `src/topomark/repo.py` | git root and file list (one `ls-files`; no links out of the repo or onto secrets), `git_objects` (many object texts from one `cat-file --batch`), gitignore-style glob matcher, secret patterns (always-secret ones, and names that are secret unless the file is source code: `SOURCE_EXT`, which leaves shell and SQL out on purpose), default excludes, guarded read (`safe_path`, `inside`), write (`write_text`: the whole file or none of it, never outside the repository and never through a link out of it or a dangling one; `outside`), `git` (always `core.fsmonitor=false`), `user_path` (what a user typed to a repo path: from the current directory if it exists there, else repo-relative; outside the repo is NOT_FOUND) | fan-in 23/3. Glob or secret changes: `tests/test_cache.py` (matcher), `tests/test_safety.py` (links, outside paths), `docs/config.md` lists |

## Interfaces and cross-area dependencies
- Used by: every command module (`Result`, `TopomarkError`, `Context`), the engine (`Config`,
  `repo.git`, `read_text`, `matches_any`), `tools/eval_nav.py` (runs `cli.main` in process),
  `tests/harness.py` (the same).
- Depends on: the standard library only (`argparse`, `tomllib`, `subprocess`) and `git` on PATH.

## Change checklist
- New global flag: `_global_flags` and `_GLOBAL_DEFAULTS` in `src/topomark/cli.py`, the global-flag list
  in `src/topomark/commands/capabilities.py`, README and `skills/topomark/SKILL.md`.
- New error code: `ERROR_CODES`, `_CODE_EXIT`, `REMEDIATION`; document it in
  `skills/topomark/reference/json-and-exit-codes.md`.
- New config key: `_ALLOWED` and `from_dict` in `src/topomark/config.py`, `docs/config.md` (table and
  example), then `python3 -m unittest tests/test_meta.py`.
- Anything here: the whole suite, `python3 -m unittest discover -s tests -t .`; the CLI smoke job in
  `.github/workflows/ci.yml` runs `bin/topomark` from a clean checkout.

## Invariants and pitfalls
- stdout is data, stderr is logs; handlers return `Result` and never print or `sys.exit`
  (`CLAUDE.md`, "Invariants").
- Exit codes are a public contract: 0 ok, 1 findings, 2 usage or refused, 3 config, 4 not found,
  5 unsupported, 6 not git, 7 internal (`src/topomark/errors.py`).
- Every text `open()` in `src/` passes `encoding="utf-8"`, writes add `newline="\n"`;
  `tests/test_meta.py` checks it by AST. Read repo files through `Context.read`, which refuses
  secret-looking paths (`SECRET_PATTERNS`, not configurable), paths that leave the repository and
  symbolic links that lead out of it or onto a secret. User-supplied paths go through
  `commands/_common.rel` and `Nav.exists`; resolving every path with `realpath` is too slow
  (a system call per component), so only paths through a link are resolved.
- Files come from git (tracked plus untracked, not ignored), never from a directory walk.
- `agent-hook` is the one command whose output is not the envelope: argparse usage errors exit 2,
  which would block a Claude Code tool call, so its action argument takes any string.

## Further reading
- `CLAUDE.md`: the invariants and how to add a command.
- `docs/config.md`: every `topomark.toml` key.
- `skills/topomark/reference/json-and-exit-codes.md`: the output contract as agents read it.
