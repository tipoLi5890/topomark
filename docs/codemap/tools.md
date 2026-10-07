---
area: tools
title: Tools
summary: Release and lint helpers, the navigation eval, the benchmark and the synthetic repo generator
granularity: file
scope:
  - tools/
---

# Tools

> Scripts for developing topomark, never shipped as commands: CI gates for manifests and the skill,
> the navigation eval and the benchmark that decide ranking and speed changes, and the generator of
> the synthetic repo both of them use. Standard library only, like the package.

## Read these first
- `tools/eval_nav.py`: how ranking changes are judged (tasks in `tools/eval/tasks.toml`).
- `tools/sync_version.py`: the release step that keeps every manifest on pyproject's version.

## Data flow and entry points
```
release:  pyproject.toml version -> sync_version.py -> .claude-plugin/*.json, .codex-plugin/plugin.json
          .claude-plugin/plugin.json -> sync_codex_manifests.py -> .codex-plugin/, .agents/plugins/
CI lint:  sync_version.py --check, sync_codex_manifests.py --check, lint_skills.py
measure:  synth_repo.py OUT -> eval_nav.py (tasks.toml, in-process CLI) / bench_nav.py (subprocesses)
```

## Files
| file | summary | impact |
|---|---|---|
| `tools/bench_nav.py` | Warm wall and CPU time of each navigation command and hook on a synthetic repo; checks what each hook prints (a wrong or missing hint is FAIL, exit 1); cProfile | fan-in 0/1. Case names refer to `tools/synth_repo.py` fixed files; `hook-post-edit-broken` runs in a scratch one-file repo; numbers go to `docs/pilots.md`. Expects the words "outline" (pre-read) and "syntax" (post-edit) in the hook text |
| `tools/eval_nav.py` | Gold rank, hit@1/@5, output tokens per task, in process with a fresh temporary cache by default (`--cache`); errors are counted apart from misses, `expect = "miss"` tasks are controls; `--compare REV` swaps only `src/` (the tasks and this script stay) and drops config keys that REV rejects | fan-in 5/1. Task format is in its docstring; `tests/test_tools.py` runs it on a tiny repo |
| `tools/lint_skills.py` | SKILL.md frontmatter, name, description <= 700 chars, size <= 15 KiB, reference links; `py_compile` of `tools/*.py` and skill scripts, `bash -n` of skill `.sh` files | fan-in 0/0. CI gate; `CLAUDE.md` names it in Commands |
| `tools/sync_codex_manifests.py` | Generate the Codex manifests from `.claude-plugin/plugin.json`; `--check` for CI | fan-in 0/0. Codex display text (`SHORT`, `LONG`, prompts) lives here |
| `tools/sync_version.py` | Stamp pyproject's version into the plugin manifests; `--check` for CI | fan-in 0/0. Step 2 of the release list in `CLAUDE.md` |
| `tools/synth_repo.py` | Deterministic multi-language synthetic git repo with fixed chain, hub and big files; `commit_all` names the branch `main` and runs none of the user's git hooks | fan-in 1/0. The eval's synth tasks and the bench name its fixed files; `tests/test_tools.py` checks determinism |

## Interfaces and cross-area dependencies
- Used by: CI (`.github/workflows/ci.yml` lint job), `tests/test_tools.py`, people measuring a change.
- Depends on: [core.md](core.md) (`cli.main`, `contract.estimate_tokens` for the eval), the plugin
  manifests in [plugin.md](plugin.md).

## Change checklist
- New eval task: write it the way an agent would ask, before tuning; gold `path#Qual.Name` must exist
  (the eval refuses stale golds with exit 2). See `CONTRIBUTING.md`, "Measuring navigation changes".
- A fixed file in `tools/synth_repo.py` changes: the eval's synth tasks and `bench_nav.py` cases.
- Changing what the gates check: `CLAUDE.md` "Commands" and the CI workflow.

## Invariants and pitfalls
- Never tune a query to the tool: when a gold answer moves with the code, update the gold only.
- Benchmarks on a busy machine: compare CPU time, not wall time (`docs/pilots.md`).
- Not every tool is read-only: `sync_version.py` and `sync_codex_manifests.py` rewrite tracked
  manifests (their `--check` modes write nothing), and `lint_skills.py`'s `py_compile` leaves
  `__pycache__/` next to the scripts it checks. The eval and the bench use a temporary cache unless
  told otherwise, never the user's.

## Further reading
- `CONTRIBUTING.md`: when to run the eval and the bench.
- `docs/pilots.md`: the numbers they produced.
