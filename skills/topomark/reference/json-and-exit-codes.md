# JSON output and exit codes

## The envelope

With `--json` (before or after the command), stdout carries exactly one JSON object and nothing
else; logs go to stderr.

```json
{"schema_version": "topomark/1", "command": "check", "ok": false, "problems": [ ... ]}
```

- `schema_version` is `topomark/1`. A major bump means a field was removed or changed meaning;
  new fields can appear at any time, so ignore keys you do not know.
- `command` is the subcommand name as typed (`tests-for`, not `tests_for`).
- Errors, including argument errors, print an error envelope on stdout and exit non-zero:

```json
{"schema_version": "topomark/1", "topomark_version": "0.1.0",
 "error": {"code": "NOT_FOUND", "message": "...", "exit": 4, "remediation": "..."}}
```

Branch on `error.code` and the exit code. Messages are for humans and may change.

One exception: `agent-hook`, which the Claude Code plugin's hooks run, answers in the hook protocol:
nothing, or one `{"hookSpecificOutput": {"hookEventName", "additionalContext"}}` object, and it
always exits 0. With `--json` (for debugging only) that object is wrapped in the envelope above.

## Exit codes

| Exit | Name | Typical cause |
|---|---|---|
| 0 | OK | ran and found nothing to report |
| 1 | FINDINGS | `check`/`stale` found problems, `doctor` found a failing check, `syntax` found a file that does not parse |
| 2 | USAGE | bad flags or arguments; also `REFUSED` (an action that would lose information, such as `init` over existing files or `stamp --baseline` over existing stamps) |
| 3 | CONFIG | `topomark.toml` is malformed or a value has the wrong type (an unknown key is only a warning on stderr) |
| 4 | NOT_FOUND | path, symbol or area does not exist; `symbol <Name>` that is ambiguous |
| 5 | UNSUPPORTED | no language adapter for the operation |
| 6 | NOT_GIT | not inside a git work tree (pass `-C <repo>`) |
| 7 | INTERNAL | a bug: rerun with `--debug` and report the traceback |

## Where the answers are

Lists come best first and are capped; the counts beside them are not.

| Command | Answers | Counts |
|---|---|---|
| `find` | `results` (`path`, `qualname`, `kind`, `start`, `end`, `signature`) | `total` |
| `search` | `results` (`path`, `qualname`, `score`, `matched`, `via`) | `total`, `files`, `truncated` |
| `locate` | `results` (`path`, `line`, `qualname`, `group`; traces add `func`, `format`) | `total`, `skipped` |
| `brief` | `related` (`path`, `role`: caller then test), plus `callers`, `tests`, `commands` | `callers_total`, `tests_total`, `trimmed` |
| `outline` (several paths) | `files` (each shaped like a single-file outline) | `total_files`, `truncated` |
| `symbol --skeleton` | `matches[].skeleton`, `matches[].elided` | |
| `tests-for` | `tests`, `commands`, `suite_commands` | `uncovered`, `limited` |
| `changes` | `files[].symbols` (`change`: added, removed, signature, body), `interface`, `review` | `counts` |
| `syntax` | `problems` (`path`, `line`, `col`, `message`, `preexisting`) | `ok`, `checked`, `skipped` |

## Discovering the surface

```bash
topomark capabilities --json
```

Lists every command, its arguments and flags (with choices), the exit-code table and the global
flags, generated from the live parser, so it never disagrees with `--help`.
