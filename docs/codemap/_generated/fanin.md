# Fan-in (generated, do not edit; approximate)

Production fan-in = how many non-test files mention a name this file declares (coupling: the callers to check when you change it). Test fan-in = how many test files mention it (guard rails). Cross-area = which other code-map areas the production callers live in.
Only top-level declarations count. Names shorter than 5 characters (except -) and names declared in more than one file (unless partial) are ignored; see the end of this file. Test files only ever reference.

| prod | test | file | area | cross-area callers |
|---:|---:|---|---|---|
| 26 | 1 | `src/topomark/errors.py` | core | commands, engine |
| 26 | 0 | `src/topomark/commands/__init__.py` | commands | core |
| 18 | 5 | `src/topomark/repo.py` | core | commands, engine, tools |
| 17 | 2 | `src/topomark/search.py` | engine | commands, core, lang, tools |
| 14 | 4 | `src/topomark/lang/registry.py` | lang | commands, core, engine, tools |
| 12 | 3 | `src/topomark/navigate.py` | engine | commands |
| 12 | 0 | `src/topomark/docs.py` | engine | commands |
| 10 | 0 | `src/topomark/workspace.py` | engine | commands |
| 9 | 0 | `src/topomark/lang/base.py` | lang | commands, engine |
| 7 | 0 | `src/topomark/lang/scan.py` | lang | engine |
| 6 | 1 | `src/topomark/contract.py` | core | commands, engine, tools |
| 5 | 2 | `src/topomark/config.py` | core | commands, engine |
| 5 | 1 | `tools/eval_nav.py` | tools | commands, engine |
| 4 | 0 | `src/topomark/stamps.py` | engine | commands |
| 3 | 2 | `src/topomark/context.py` | core | engine |
| 3 | 1 | `src/topomark/graph.py` | engine |  |
| 3 | 1 | `src/topomark/index.py` | engine | commands |
| 3 | 1 | `src/topomark/lang/brace.py` | lang |  |
| 2 | 3 | `src/topomark/cli.py` | core | commands, tools |
| 2 | 1 | `src/topomark/syntax.py` | engine | commands |
| 2 | 0 | `src/topomark/commands/_common.py` | commands |  |
| 2 | 0 | `src/topomark/lang/python.py` | lang | core |
| 1 | 1 | `src/topomark/changes.py` | engine | commands |
| 1 | 1 | `src/topomark/lang/csharp.py` | lang |  |
| 1 | 1 | `src/topomark/lang/simple.py` | lang |  |
| 1 | 1 | `src/topomark/locate.py` | engine | commands |
| 1 | 0 | `tools/synth_repo.py` | tools |  |
| 0 | 1 | `src/topomark/lang/extra.py` | lang |  |
| 0 | 1 | `tools/bench_nav.py` | tools |  |
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
| `tests/test_cache.py` | 6 | `src/topomark/repo.py`, `src/topomark/search.py`, `src/topomark/lang/registry.py`, `src/topomark/context.py`, `src/topomark/graph.py`, `src/topomark/index.py` |
| `tests/test_changes.py` | 1 | `src/topomark/changes.py` |
| `tests/test_docsystem.py` | 1 | `src/topomark/repo.py` |
| `tests/test_lang.py` | 1 | `src/topomark/lang/registry.py` |
| `tests/test_lang_scan.py` | 4 | `src/topomark/lang/brace.py`, `src/topomark/lang/csharp.py`, `src/topomark/lang/simple.py`, `src/topomark/lang/extra.py` |
| `tests/test_locate.py` | 1 | `src/topomark/locate.py` |
| `tests/test_meta.py` | 4 | `src/topomark/repo.py`, `src/topomark/search.py`, `src/topomark/config.py`, `src/topomark/cli.py` |
| `tests/test_navigation.py` | 3 | `src/topomark/lang/registry.py`, `src/topomark/navigate.py`, `src/topomark/contract.py` |
| `tests/test_regressions.py` | 1 | `src/topomark/lang/registry.py` |
| `tests/test_safety.py` | 2 | `src/topomark/repo.py`, `src/topomark/navigate.py` |
| `tests/test_syntax.py` | 3 | `src/topomark/navigate.py`, `src/topomark/context.py`, `src/topomark/syntax.py` |
| `tests/test_tools.py` | 6 | `src/topomark/errors.py`, `src/topomark/repo.py`, `src/topomark/config.py`, `tools/eval_nav.py`, `src/topomark/cli.py`, `tools/bench_nav.py` |
