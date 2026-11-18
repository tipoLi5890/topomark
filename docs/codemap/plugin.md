---
area: plugin
title: Agent plugin
summary: The agent skill, the Claude Code hooks and plugin manifest that ship with the repo
granularity: file
scope:
  - skills/
  - hooks/
  - .claude-plugin/
---

# Agent plugin

> What an agent working in *another* repository gets from topomark: the `topomark` skill (when to
> use which command, the core loop, references loaded on demand), the Claude Code hooks that run
> `agent-hook`, and the hand-edited Claude manifests. The Codex manifests (`.codex-plugin/`,
> `.agents/`) are generated from these by `tools/sync_codex_manifests.py` and have no rows. Agents
> working *on* topomark read `CLAUDE.md` instead.

## Read these first
- `skills/topomark/SKILL.md`: the loop and the cheat sheet; under 15 KB by gate.
- `hooks/hooks.json`: the three hooks and their matchers.

## Data flow and entry points
```
/plugin install topomark@topomark  (Claude Code reads .claude-plugin/marketplace.json, plugin.json)
  skills/topomark/SKILL.md         loaded when the description matches the request
    reference/*.md                 read when SKILL.md's "Load what the situation needs" points there
  hooks/hooks.json                 SessionStart / PreToolUse(Read) / PostToolUse(Edit|Write|MultiEdit)
    -> "${CLAUDE_PLUGIN_ROOT}"/bin/topomark agent-hook <action>   (5 s timeout, never blocks)
Codex: tools/sync_codex_manifests.py writes .codex-plugin/plugin.json and .agents/plugins/marketplace.json
```

## Files
| file | summary | impact |
|---|---|---|
| `.claude-plugin/marketplace.json` | Claude Code marketplace entry for this repo, plugin version | fan-in 0/0. Version is stamped by `tools/sync_version.py` from pyproject.toml |
| `.claude-plugin/plugin.json` | Claude plugin manifest: name, version, description, author, keywords | fan-in 0/0. Source of the Codex manifests: run `python3 tools/sync_codex_manifests.py` after editing |
| `hooks/hooks.json` | Claude Code hooks: session-start, pre-read and post-edit, each `agent-hook` with a 5 s timeout | fan-in 0/0. Must match `src/topomark/commands/agent_hook.py` actions; `tests/test_agent_hook.py` parses each command |
| `skills/topomark/SKILL.md` | The skill: prerequisites, when to use which command, core loop, cheat sheet, exit codes | fan-in 0/0. `python3 tools/lint_skills.py` (15 KB, 700-char description); bash lines parse (`tests/test_meta.py`) |
| `skills/topomark/reference/adoption.md` | Setting topomark up in a repo: dry run, init, draft, baseline, gate; the plugin hooks | fan-in 0/0. Update when `init`, `draft`, `stamp` or the hooks change |
| `skills/topomark/reference/code-map.md` | Writing area rows; every `check` problem code and how to clear it; what a stamp covers | fan-in 0/0. A new problem code in `src/topomark/workspace.py` gets a row here |
| `skills/topomark/reference/commands.md` | Every navigation command with flags, examples, ranking rules and JSON fields | fan-in 0/0. Any navigation flag or JSON field change lands here |
| `skills/topomark/reference/json-and-exit-codes.md` | The `--json` envelope, error envelope, exit codes, where each command's answers are | fan-in 0/0. Exit or envelope changes in `src/topomark/cli.py` and `src/topomark/errors.py` land here |

## Interfaces and cross-area dependencies
- Used by: Claude Code and Codex (the skill), Claude Code (the hooks); README links the skill.
- Depends on: [commands.md](commands.md) (`agent-hook` and every command the skill names),
  [core.md](core.md) (`bin/topomark`, which the hooks run).

## Change checklist
- A command, flag or JSON field changes: the cheat sheet in `skills/topomark/SKILL.md`, the
  matching reference file, README and the translated READMEs in `.github/`.
- A hook changes: `hooks/hooks.json`, `src/topomark/commands/agent_hook.py`,
  `skills/topomark/reference/adoption.md` (hooks section), README "Using it from an agent".
- A manifest changes: `python3 tools/sync_version.py --check` and
  `python3 tools/sync_codex_manifests.py --check` (both CI gates).

## Invariants and pitfalls
- The hook commands never pass `--json` and the hooks never set a permission decision; `agent-hook`
  exits 0 whatever happens (`skills/topomark/reference/adoption.md`).
- `.claude-plugin/plugin.json` needs no `hooks` key: Claude Code loads `hooks/hooks.json` from the
  plugin root and merges any hooks the manifest declares into it (plugins reference, "How each key
  combines with its default location").
- The hook `timeout` is in seconds.
- Skill text is English; the only translated documents are the READMEs in `.github/`: Traditional
  Chinese (Taiwan usage), Simplified Chinese (mainland usage) and Japanese, with full-width
  punctuation and no dashes.

## Further reading
- `README.md`, "Using it from an agent": the hooks and the one-line instruction for AGENTS.md.
