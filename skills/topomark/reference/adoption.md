# Adopting topomark in a repository

## 1. Look before writing

```bash
topomark doctor
topomark init --dry-run
topomark init --dry-run --json
```

`--dry-run` writes nothing. Review the proposal with the user before writing:

- **Areas.** One per directory that holds a project manifest (`pyproject.toml`, `package.json`,
  `pubspec.yaml`, `*.asmdef`, `go.mod`, `Cargo.toml`, `build.gradle(.kts)`, `*.csproj`,
  `wrangler.jsonc`...). A directory with two or more manifest children is split into them; a
  directory where one manifest child holds nearly all the code is replaced by it; leftovers join an
  `other` area. Test trees stay one area.
- **Granularity.** Areas over about 60 code files get `granularity: dir` (one row per directory);
  `depth: 2` when one directory would hold most of the files.
- **Excludes.** Generated code (Flutter `app_localizations*.dart`, `*.g.dart`, protobuf output...)
  and code inside dot-directories (`.claude/`, `.github/`) are suggested as excludes.
- **Rule files.** Existing CLAUDE.md, AGENTS.md, ARCHITECTURE.md, REPO_MAP.md, CODE.md and
  `docs/_overview/` are linked from L0 (nested ones from their area file) instead of being copied.
- `unowned` and `conflicts` in the JSON should both be empty.

## 2. Write the skeleton

```bash
topomark init
topomark init --docs-dir docs/map
```

It writes `topomark.toml`, `<docs_dir>/README.md`, `<docs_dir>/_TEMPLATE.md` and one file per area,
and refuses (writing nothing) when any of them exists; `--force` overwrites. Rename areas, merge or
split scopes, and fix summaries now: it is cheapest before rows exist.

## 3. Fill the rows

```bash
topomark draft backend
topomark draft backend --write
topomark gen
topomark check --no-stamps
```

`draft --write` appends one row per missing unit under the area's file table, summary and fan-in
prefilled. Then read each file and correct its row; prefilled text is a starting point. Fill in L0's
"to change X, read this first" table and the highest-impact files from `_generated/fanin.md`.

## 4. Baseline and gate

```bash
topomark stamp --baseline
topomark check
topomark hook install
```

`stamp --baseline` records every unit as reviewed; run it once, after the rows were actually read.
From then on `check` fails when a unit's interface changes without its row being reviewed. The hook
is opt-in, per clone, and keeps an existing pre-commit hook as `pre-commit.local`.

## Claude Code plugin hooks

Installed as a Claude Code plugin, topomark also registers three hooks in `hooks/hooks.json`. Each
runs `"${CLAUDE_PLUGIN_ROOT}"/bin/topomark agent-hook <action>` with a 5-second timeout (the hook
`timeout` is in seconds) and only adds context for the agent:

| Event (matcher) | Action | What the agent sees |
|---|---|---|
| SessionStart (`startup`, `clear`, `compact`) | `session-start` | the L0 path, each area's name and file, one line of navigation commands and whether review stamps exist; at most 40 lines and 4 KB, no L0 prose. Without a code map, one line suggesting `topomark map --tokens 2000` |
| PreToolUse (`Read`) | `pre-read` | a file over 400 lines: outline it first, then `symbol --skeleton` or a ranged read; the first file read in an area: its area file. Each hint once per session. Nothing for a ranged read (`offset`/`limit`) or a file without a language adapter, outside the repo, secret-looking or excluded |
| PostToolUse (`Edit`, `Write`, `MultiEdit`) | `post-edit` | the `syntax` check of the edited file, only when it no longer parses and its HEAD version did |

The hooks never block a tool call and never answer a permission prompt: they print nothing or one
`{"hookSpecificOutput": {"hookEventName", "additionalContext"}}` object and exit 0 whatever happens
(outside a git repo or with a broken payload they stay silent; an invalid `topomark.toml` gets one
line at session start pointing at `topomark doctor`). This output follows the hook protocol, not the `--json` envelope. The hints already given are remembered
per session as marker files in the user cache directory (`agent-hook/` beside the analysis cache);
after `/clear` or a compaction a hint can come once more. Try one by hand with
`echo '{"cwd": "."}' | topomark agent-hook session-start`.

Codex and other agents have no such hooks: the skill tells them to run `topomark syntax --diff`
after every edit.

## Repos that already have a hand-written map

If a code map exists at the target `docs_dir`, `init` reports every file it would overwrite and
refuses. Point `--docs-dir` elsewhere to compare, or keep the existing files and add only the
frontmatter `check` needs (`area`, `title`, `summary`, `scope`).
