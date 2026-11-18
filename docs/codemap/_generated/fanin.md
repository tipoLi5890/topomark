# Fan-in (generated, do not edit; approximate)

Production fan-in = how many non-test files mention a name this file declares (coupling: the callers to check when you change it). Test fan-in = how many test files mention it (guard rails). Cross-area = which other code-map areas the production callers live in.
Only top-level declarations count. Names shorter than 5 characters (except -) and names declared in more than one file (unless partial) are ignored; see the end of this file. Test files only ever reference.

| prod | test | file | area | cross-area callers |
|---:|---:|---|---|---|
| 31 | 2 | `src/topomark/context.py` | core | commands, engine |
| 26 | 1 | `src/topomark/commands/__init__.py` | commands | core |
| 26 | 1 | `src/topomark/errors.py` | core | commands, engine |
| 24 | 0 | `src/topomark/lang/base.py` | lang | commands, engine |
| 23 | 3 | `src/topomark/repo.py` | core | commands, engine |
| 13 | 0 | `src/topomark/docs.py` | engine | commands |
| 13 | 0 | `src/topomark/lang/scan.py` | lang | engine |
| 11 | 1 | `src/topomark/navigate.py` | engine | commands |
| 10 | 4 | `src/topomark/lang/registry.py` | lang | commands, core, engine, tools |
| 10 | 0 | `src/topomark/workspace.py` | engine | commands |
| 8 | 1 | `src/topomark/lang/brace.py` | lang |  |
| 6 | 1 | `src/topomark/config.py` | core | commands, engine |
| 6 | 1 | `src/topomark/contract.py` | core | commands, engine, tools |
| 6 | 0 | `src/topomark/lang/_imports.py` | lang |  |
| 5 | 0 | `src/topomark/testsel.py` | engine | commands |
| 4 | 1 | `src/topomark/graph.py` | engine |  |
| 4 | 1 | `src/topomark/masking.py` | engine |  |
| 4 | 0 | `src/topomark/lang/_decl.py` | lang |  |
| 3 | 1 | `src/topomark/index.py` | engine | commands |
| 3 | 1 | `src/topomark/runners.py` | engine | commands |
| 3 | 0 | `src/topomark/stamps.py` | engine | commands |
| 2 | 3 | `src/topomark/cli.py` | core | commands, tools |
| 2 | 1 | `src/topomark/imports.py` | engine |  |
| 2 | 1 | `src/topomark/syntax.py` | engine | commands |
| 2 | 0 | `src/topomark/commands/_common.py` | commands |  |
| 2 | 0 | `src/topomark/lang/python.py` | lang | core |
| 2 | 0 | `src/topomark/search.py` | engine | commands |
| 1 | 1 | `src/topomark/changes.py` | engine | commands |
| 1 | 1 | `src/topomark/lang/cfamily.py` | lang |  |
| 1 | 1 | `src/topomark/lang/csharp.py` | lang |  |
| 1 | 1 | `src/topomark/lang/kotlin.py` | lang |  |
| 1 | 1 | `src/topomark/lang/simple.py` | lang |  |
| 1 | 1 | `src/topomark/lang/swift.py` | lang |  |
| 1 | 1 | `src/topomark/locate.py` | engine | commands |
| 1 | 0 | `src/topomark/ranking.py` | engine | commands |
| 1 | 0 | `tools/synth_repo.py` | tools |  |
| 0 | 1 | `tools/bench_nav.py` | tools |  |
| 0 | 1 | `tools/eval_nav.py` | tools |  |
| 0 | 0 | `src/topomark/commands/capabilities.py` | commands |  |
| 0 | 0 | `src/topomark/commands/draft.py` | commands |  |
| 0 | 0 | `src/topomark/commands/init.py` | commands |  |
| 0 | 0 | `tools/lint_skills.py` | tools |  |
| 0 | 0 | `tools/sync_version.py` | tools |  |

Names not counted (26 short, 8 declared in several files):

```
short: Area, Dart, Data, Decl, Go, Hit, Java, JsTs, Nav, Rust, Site, Sql, add, clip, fail, git, h16, load, main, mask, norm, rel, run, slug, stem, sync
ambiguous: generate, git_files, main, parse_frontmatter, register, render, run, strip_jsonc
```

## Test file → production files it mentions

| test file | count | production files (by fan-in) |
|---|---:|---|
| `tests/test_agent_hook.py` | 1 | `src/topomark/cli.py` |
| `tests/test_cache.py` | 5 | `src/topomark/context.py`, `src/topomark/repo.py`, `src/topomark/lang/registry.py`, `src/topomark/graph.py`, `src/topomark/index.py` |
| `tests/test_changes.py` | 1 | `src/topomark/changes.py` |
| `tests/test_lang.py` | 1 | `src/topomark/lang/registry.py` |
| `tests/test_lang_scan.py` | 6 | `src/topomark/lang/brace.py`, `src/topomark/lang/cfamily.py`, `src/topomark/lang/csharp.py`, `src/topomark/lang/kotlin.py`, `src/topomark/lang/simple.py`, `src/topomark/lang/swift.py` |
| `tests/test_locate.py` | 1 | `src/topomark/locate.py` |
| `tests/test_meta.py` | 3 | `src/topomark/commands/__init__.py`, `src/topomark/config.py`, `src/topomark/cli.py` |
| `tests/test_navigation.py` | 4 | `src/topomark/navigate.py`, `src/topomark/lang/registry.py`, `src/topomark/contract.py`, `src/topomark/imports.py` |
| `tests/test_regressions.py` | 1 | `src/topomark/lang/registry.py` |
| `tests/test_safety.py` | 3 | `src/topomark/errors.py`, `src/topomark/repo.py`, `src/topomark/runners.py` |
| `tests/test_syntax.py` | 3 | `src/topomark/context.py`, `src/topomark/masking.py`, `src/topomark/syntax.py` |
| `tests/test_tools.py` | 4 | `src/topomark/repo.py`, `src/topomark/cli.py`, `tools/bench_nav.py`, `tools/eval_nav.py` |
