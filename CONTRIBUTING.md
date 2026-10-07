# Contributing to topomark

Thanks for helping. topomark is small on purpose; most of the rules below exist to keep it that way.

## Project invariants (please don't break these)

- **Standard library only**, Python 3.11+. A pull request that adds a runtime dependency will not be
  merged; dev tools (ruff, mypy) run in CI only.
- **Offline and read-only** on the repositories it maps, except the files a command owns
  (`topomark.toml`, `docs_dir`, `.git/hooks/pre-commit`). `init --dry-run` writes nothing.
- **Secret-looking paths are never read.**
- **Exit codes and `--json` fields are a public contract.** Add fields freely; removing or renaming
  one is a major `schema_version` bump.
- **Explicit text I/O**: `encoding="utf-8"` on every open/read/write, `newline="\n"` on writes.

The full list, with the reasons, is in [CLAUDE.md](CLAUDE.md).

## Dev setup

```bash
git clone https://github.com/tipoLi5890/topomark && cd topomark
python3 -m unittest discover -s tests -t .
bin/topomark --version
```

No virtualenv is needed to run the tests. To run the linters locally the way CI does:

```bash
python3 -m pip install ruff mypy
ruff check src tests tools
mypy
```

## Before opening a pull request

- [ ] `python3 -m unittest discover -s tests -t .` is green.
- [ ] New behaviour has a test using `tests.harness.TempRepo`.
- [ ] New commands or flags are in README.md and `skills/topomark/SKILL.md`; `topomark ...` lines
      in ```bash blocks parse (the meta test checks this).
- [ ] `python3 tools/sync_version.py --check`, `python3 tools/sync_codex_manifests.py --check` and
      `python3 tools/lint_skills.py` pass.
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`.

## Measuring navigation changes

Changes to ranking, output size or speed are judged by numbers:

```bash
python3 tools/eval_nav.py                  # gold rank, hit@1/hit@5, tokens, time per task in tools/eval/tasks.toml
python3 tools/eval_nav.py --compare main   # the same tasks with topomark's src/ from another rev
python3 tools/bench_nav.py --runs 3        # warm timings on a generated 3,000-file repo (tools/synth_repo.py)
```

Write eval tasks the way an agent would ask, before tuning anything, and never tune a query to
the tool: when a gold answer moves with the code, update the gold only.

## Language adapters

An adapter turns `(path, text)` into a `FileInfo` (`src/topomark/lang/base.py`). Keep it lexical:
mask comments and strings, track scopes, read declarations. The *surface* must change when the
public interface or header changes and must not change when only a body changes; add a test for
both directions.

## Reporting bugs

Include `topomark --version`, `topomark doctor --json`, the command you ran and its output with
`--debug`. Do not attach files from private repositories; a minimal reproduction in a fresh
`git init` directory is best.
