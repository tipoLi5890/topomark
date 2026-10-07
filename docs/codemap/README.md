# Code map (L0): start here

topomark's own code map, kept by topomark. Read only as deep as the task needs: this page, then one
area file, then the code by symbol (`topomark outline <file>`, `topomark symbol <file>#<Name>`,
`topomark brief <file>`). Area files follow [_TEMPLATE.md](_TEMPLATE.md).

The rules for working on topomark (invariants, commands, adding a command, releases) live in
`CLAUDE.md`; `CONTRIBUTING.md` has the pull-request checklist. This map links them and does not
repeat them.

Generated numbers (`topomark gen`, never edit by hand): [_generated/fanin.md](_generated/fanin.md).

## Areas

| area | file | what it owns | scope |
|---|---|---|---|
| core | [core.md](core.md) | launcher, CLI dispatch and output contract, `Context`, config, errors, git file list, secrets | `bin/`, `src/topomark/cli.py` and the other entry modules |
| commands | [commands.md](commands.md) | one module per command: arguments, handler, rendering; `init`'s templates | `src/topomark/commands/`, `src/topomark/templates/` |
| engine | [engine.md](engine.md) | analysis cache, reference graph, code-map documents and `check`, stamps, navigation, search, locate, changes, syntax | `src/topomark/` (the rest) |
| lang | [lang.md](lang.md) | language adapters: one file to a `FileInfo` (symbols, header, surface, identifiers, imports) | `src/topomark/lang/` |
| plugin | [plugin.md](plugin.md) | the agent skill, the Claude Code hooks, the Claude plugin manifests | `skills/`, `hooks/`, `.claude-plugin/` |
| tools | [tools.md](tools.md) | release and lint gates, navigation eval, benchmark, synthetic repo | `tools/` |
| tests | [tests.md](tests.md) | the unittest suite and its harness (fixtures excluded) | `tests/` |

Layering, top to bottom: plugin → commands → engine → lang; core is used by all of them. tools and
tests drive the CLI from outside.

## To change X, read this first

| the change | read first | then |
|---|---|---|
| add a command | [commands.md](commands.md) | `CLAUDE.md` "Adding a command"; [plugin.md](plugin.md) for the skill and references |
| add a flag or JSON field | [commands.md](commands.md) | `skills/topomark/reference/commands.md`, `skills/topomark/reference/json-and-exit-codes.md` |
| change the output envelope or exit codes | [core.md](core.md) | `tests/test_meta.py`; README and skill exit tables |
| add a `topomark.toml` key | [core.md](core.md) | `docs/config.md` (its example is parsed by a test) |
| add or fix a language adapter | [lang.md](lang.md) | `tests/test_lang.py` goldens; the language lists in README and `docs/concepts.md` |
| change what a review surface contains | [lang.md](lang.md) | every adopted map reports `STAMP_CHANGED`: CHANGELOG note |
| change search, find, locate or test ranking | [engine.md](engine.md) | `python3 tools/eval_nav.py --compare HEAD`; numbers into `docs/pilots.md` |
| change caching or anything per file | [engine.md](engine.md) | `CACHE_FORMAT` in `src/topomark/index.py`; `python3 tools/bench_nav.py` |
| add a `check` problem | [engine.md](engine.md) | `skills/topomark/reference/code-map.md` |
| change a plugin hook | [plugin.md](plugin.md) | `src/topomark/commands/agent_hook.py`, `tests/test_agent_hook.py` |
| release | [tools.md](tools.md) | `CLAUDE.md` "Releases" |

## Highest-impact files

From [_generated/fanin.md](_generated/fanin.md): production / test files that mention a name the file
declares. Approximate: a name that collides with something common inflates the count.

| prod / test | file | area | why it reaches everything |
|---:|---|---|---|
| 26/0 | `src/topomark/commands/__init__.py` | commands | `Result`, returned by every handler |
| 24/0 | `src/topomark/errors.py` | core | `TopomarkError` and the exit table, raised everywhere |
| 17/3 | `src/topomark/repo.py` | core | git file list, glob matching and `read_text` for every command |
| 14/4 | `src/topomark/lang/registry.py` | lang | the only way from a path to an adapter |
| 12/1 | `src/topomark/navigate.py` | engine | `Nav` behind every navigation command |
| 12/0 | `src/topomark/docs.py` | engine | areas, ownership and units behind every code-map command |
| 10/0 | `src/topomark/workspace.py` | engine | the code-map state `check`, `stamp`, `stale`, `gen`, `sync` share |

`src/topomark/search.py` shows 16/1 only because its `search` function shares a name with `re.search`;
its one real caller is `src/topomark/commands/search.py`.

## Cross-area coupling

- [commands.md](commands.md) imports [engine.md](engine.md) inside each `run`, never at module load
  (keeps `--help` and every hook call fast).
- [plugin.md](plugin.md)'s `hooks/hooks.json` calls `bin/topomark` ([core.md](core.md)) with an
  `agent-hook` action ([commands.md](commands.md)); the three must agree.
- [engine.md](engine.md)'s cache is invalidated by any edit under `src/topomark/lang/`
  ([lang.md](lang.md)): the index fingerprint hashes the adapters.
- [tests.md](tests.md) reach most modules through `cli.main` and `commands/__init__.py`'s computed
  imports, which `tests-for` cannot follow: for engine changes it may print few tests, run the suite.

## Maintenance

```bash
topomark check            # coverage, dead paths, ownership, line caps, fan-in, generated files, stamps
topomark changes          # before committing: interface vs body changes and the rows to review
topomark diff src/topomark/navigate.py   # what changed in a unit since its review
topomark stamp src/topomark/navigate.py  # after reading the row and finding it still true
topomark draft engine     # rows an area file is missing
topomark gen              # regenerate _generated/ after the structure changed
topomark sync             # rewrite fan-in numbers in area files
```

After an interface change: `topomark diff <unit>`, update the row, then `topomark stamp <unit>`.
Never stamp to make `check` green. Stamps live in [stamps.json](stamps.json); `check` runs in CI.
