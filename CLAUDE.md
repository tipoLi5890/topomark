# CLAUDE.md

Guidance for agents working **on** topomark itself. (Agents *using* topomark in another repo: read
`skills/topomark/SKILL.md`.)

## Commands

```bash
python3 -m unittest discover -s tests -t .      # the whole suite (stdlib unittest, no pytest)
python3 -m unittest tests.test_init_draft       # one module
bin/topomark --version                          # run from the checkout, no install
python3 -m topomark capabilities --json         # with PYTHONPATH=src
python3 tools/sync_version.py --check           # manifests match pyproject
python3 tools/sync_codex_manifests.py --check   # .codex-plugin/ and .agents/ generated from .claude-plugin/
python3 tools/lint_skills.py                    # SKILL.md frontmatter and size gates
```

ruff and mypy run in CI only (`pip install ruff mypy` there); their settings are in `pyproject.toml`.

## Invariants (tests enforce most of them; don't regress)

- **Zero runtime dependencies.** Standard library only, Python >= 3.11 (`tomllib`). No PyYAML, no
  tree-sitter, no network access. Dev tools stay out of `[project.dependencies]`.
- **Text I/O is explicit.** Every `open()`, `read_text()` and `write_text()` in `src/` passes
  `encoding="utf-8"`; every text write also passes `newline="\n"` (`tests/test_meta.py` checks it by
  AST). Read repo files through `repo.read_text`, which refuses secret-looking paths and normalises
  CRLF. Write through `repo.write_text`.
- **stdout is data, stderr is logs.** `--json` prints exactly one object with `schema_version` and
  `command`; errors print the error envelope on stdout. Handlers return `Result(data, text, exit)`
  and never print.
- **Exit codes are a contract** (`errors.EXIT`): 0 ok, 1 findings, 2 usage/refused, 3 config,
  4 not found, 5 unsupported, 6 not git, 7 internal. Raise `TopomarkError(code, message)`; never
  `sys.exit` from a handler.
- **Read-only on target repos** except the files a command owns: `init` (topomark.toml and
  `docs_dir`), `draft --write`, `gen`, `sync`, `stamp` (`docs_dir`), `hook` (`.git/hooks`).
  `init --dry-run` writes nothing, anywhere. The analysis cache lives in the user cache directory.
- **Files come from git**, secrets are never read (`repo.SECRET_PATTERNS`, not configurable).
- **One module per command** in `src/topomark/commands/`, listed in `commands._NAMES`, exposing
  `register(sub, common)` and `run(args, ctx) -> Result`. Heavy imports go inside `run` so `--help`
  stays fast. `capabilities` reads the live parser, so a command can't exist undescribed.
- **Docs are executable.** Every `topomark ...` line in a ```bash block of README.md, docs/,
  skills/ and the templates must parse with the real parser (`tests/test_meta.py`).
- **zh-Hant text** (templates, `.github/README.zh-Hant.md`) uses Taiwan usage and full-width
  punctuation, and never a dash (— or ——).

## Adding a command

1. `src/topomark/commands/<name>.py` with `register` and `run`; add the name to `commands._NAMES`
   (underscores become the module name; the CLI name is what `add(sub, common, "<cli-name>", ...)`
   registers).
2. Tests in `tests/` using `tests.harness.TempRepo` (a throwaway git repo) and `repo.json(...)`.
3. Document it in README.md (command table), `skills/topomark/SKILL.md` (cheat sheet) and, for
   navigation commands, `skills/topomark/reference/commands.md`.
4. `CHANGELOG.md` under `[Unreleased]`.

## Releases

1. Bump `[project].version` in `pyproject.toml`.
2. `python3 tools/sync_version.py` then `python3 tools/sync_codex_manifests.py`.
3. Move `[Unreleased]` to `[x.y.z] - YYYY-MM-DD` in `CHANGELOG.md`, add the compare link.
4. Full suite green, `python3 tools/lint_skills.py`, both `--check` tools green.
5. Commit, tag `vX.Y.Z`, push the tag.

## Layout

| Path | What |
|---|---|
| `src/topomark/cli.py` | argparse dispatch, global flags, JSON envelope, exit codes |
| `src/topomark/commands/` | one module per command |
| `src/topomark/lang/` | language adapters → `FileInfo` (symbols, header, surface, idents) |
| `src/topomark/workspace.py` | areas, units, fan-in, generated reports, `check` problems |
| `src/topomark/docs.py` | area frontmatter, ownership, units |
| `src/topomark/stamps.py` | review stamps |
| `src/topomark/navigate.py` | shared engine for the navigation commands |
| `src/topomark/templates/{en,zh-Hant}/` | `init` templates (package data) |
| `skills/topomark/` | the agent skill |
| `tools/` | release and lint helpers (stdlib only) |
