# Changelog

All notable changes to `topomark` are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning policy

- **Package version (SemVer).** The single source of truth is `pyproject.toml`;
  `tools/sync_version.py` stamps it into `.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json` and `.codex-plugin/plugin.json`, and CI fails on drift.
  MAJOR = a backwards-incompatible change to the CLI surface, the JSON output, the exit codes or the
  on-disk formats; MINOR = new commands, flags, adapters or checks; PATCH = fixes.
- **`schema_version`** (`topomark/1`, in every `--json` payload; `topomark.contract.SCHEMA_VERSION`).
  Fields may be added at any time; the major part is bumped only when a field is removed or changes
  meaning.
- **`stamps.json` format** (`version: 2`, `topomark.contract.STAMPS_VERSION`). A new format is read as
  foreign and reported as `STAMPS_FORMAT`; `topomark stamp --baseline --force` migrates after review.

## [Unreleased]

## [0.3.0] - 2026-10-09

### Added

- `outline` warns when a file's outline may be incomplete (JSON: `degraded`): a Python bracket that
  never closes hides every declaration after it, and a JS/TS file whose braces do not balance
  outside strings and comments may have one cut short. The adapters read text and do not parse, so
  until now such a file was listed short without a word. Cache format 3: the first run after
  upgrading re-parses.

### Fixed

- C# and Java fields whose type has several type arguments were named after one of them
  (`Map<String, Integer> counts` was listed as `String`, `Dictionary<string, int> lookup` as
  `string`): `outline`, `symbol`, `find` and `search` now show the field's own name. Signatures,
  and with them the review surface and the stamps, are unchanged, and so is fan-in (it counts
  top-level types). Java has a golden outline in
  the tests now, which is how this was found.
- C#: a member whose type is a tuple was named after its modifier (`public (int, string) pair` and
  `public (int, string) Find(int id)` were both a method called `public`), and a field holding a
  lambda was a property named after the lambda's parameter (`Func<int, int> twice = x => x * 2` was
  `x`). They are now `pair`, `Find` and `twice`.
- C, C++ and Objective-C: a declaration with long identifiers could take seconds to read, or never
  finish. The pattern that looks for function pointers tried every way of cutting an identifier
  into pieces before giving up (exponential in its length): a 2 KB header with a constructor like
  `explicit Terminal(NamedPipe &output, bool plainMode, ...)` took two seconds, larger files hung
  `map`, `check` and the first run of anything that indexes the repository. Each word is now
  matched whole; 14,000 installed JS, TS and C-family files that took minutes parse in 15 seconds.
- A signature longer than 200 characters was cut before it reached the review surface (JS/TS, Dart,
  Kotlin, Swift, Go, Rust, C, C++, Objective-C), so a parameter added past the cut did not ask for
  a review. Outlines still show the first 200 characters; the surface now holds the whole
  signature.
- `changes` read wrong paths when the user's git sets `diff.noprefix` or `diff.mnemonicPrefix`
  (`src/x.py` came out as `c/x.py`, listed as added): the diff is now asked for with fixed `a/` and
  `b/` prefixes.
- A `docs_dir` that leaves the repository (`../elsewhere`) is refused: `init --docs-dir` with a
  usage error (exit 2, `--dry-run` included), `docs_dir` in `topomark.toml` with a config error
  (exit 3). `init` used to plan, and write, files outside the repository.
- `topomark --json` with no command prints the error envelope on stdout (it printed the help text
  on stderr and nothing on stdout).
- A reader that closes the pipe early (`topomark outline src --json | head -c 100`) no longer ends
  in a traceback: the command stops quietly with its own exit code.
- A `stamps.json` that is not JSON (merge-conflict markers) is a config error (exit 3) that names
  the file, not an internal error (exit 7).

### Changed

- The analysis cache no longer throws away other indexes the moment a new one appears: an index
  written by another topomark version or Python stays for 14 days after its last use, so a plugin
  and a pip install on different versions stop re-parsing the repository in turn. Cache folders of
  repositories not opened for 90 days, and temporary files a killed run left, are removed. Two runs
  at once (the hooks start a process per tool call) merge their entries into a shard instead of the
  later one writing the shard back as it first read it.
- Fewer git processes: one `ls-files` per command instead of two, and `changes` reads every old
  version through one `git cat-file --batch` instead of a `git show` per file.
- Files topomark writes (`stamps.json`, area files, generated reports) are written whole or not at
  all: a temporary file is renamed into place.
- **Stamps survive adapter changes.** When a stamped surface hash no longer matches, `check`, `stale`
  and `diff` read the reviewed content again (the git blobs a stamp records) with the adapters of
  the running version and compare that with the files as they are. An upgrade that reads a
  declaration differently (the C# and long-signature fixes below) no longer reports
  `STAMP_CHANGED` for code nobody touched; only a stamp whose reviewed blob git has pruned falls
  back to comparing hashes. `check` still writes nothing: the stored hash is refreshed the next time the unit
  is stamped. Until then each `check` re-reads what differs in two git processes (0.2 s to 0.3 s
  for 227 units on the 3,000-file synthetic repo when every stamp is from another reading).
- **Fan-in between Python files needs an import.** A Python file that mentions a name another
  Python file declares counts as a reference only when it imports that module, directly or through a
  module that imports it and mentions the name (a re-export, a package `__init__`). Until now the
  identifier alone counted, so a module with a function called `search` collected every file that
  calls `re.search` (19/2 in topomark's own map, 2/0 now). Other languages, mixed pairs and files
  that load modules by computed names are judged by name as before. This changes `impact`, `brief`,
  `map`'s ranking and `tests-for`'s callers for Python code, and the numbers in adopted code maps:
  after upgrading, `check` reports `FANIN_STALE`, `GENERATED_STALE` and possibly `EDGES_CHANGED`
  once. Run `topomark sync`, `topomark gen`, and after reading the cross-area sections
  `topomark stamp --edges <area>`.
- The adapters for Dart, Kotlin, Swift, Go, Rust and the C family each have a module of their own
  (`lang/extra.py` held all six), and every adapter is registered in one table. An adapter that
  fails to import is now an error instead of six languages quietly falling back to plain text.
  Their output is unchanged (compared on 12,000 files).
- `navigate.py` (1,192 lines) is five modules smaller: `masking.py`, `imports.py`, `testsel.py`,
  `runners.py` and `ranking.py` hold what their names say, and `rel` lives in `repo.user_path`.
  Nothing moved for users: the eval and the JSON of sixteen commands are byte-identical before and
  after. An edit to runner quoting or `map`'s ranking no longer invalidates the cached search index,
  and `syntax.check_file` (the post-edit hook) no longer imports the workspace to mask a file.
- A section or key in `topomark.toml` that this version does not know is ignored with a `warning:`
  line on stderr (hidden by `--quiet`) instead of a config error (exit 3): a file written for a
  newer topomark no longer stops an older one, which matters when the plugin and a pip install are
  on different versions. The plugin hooks never print the warning. Wrong types are still config errors, and more of them are caught:
  `include_default_excludes` must be a boolean; a runner's `match`, `command`, `names`, `join` and
  `fallback` must be strings and `max_names` a positive integer (`max_names = "many"` was an
  internal error, exit 7).
- Secret-looking paths. More are refused: `secrets.yaml`/`.yml`, `*.secrets.yaml`/`.yml`,
  `.git-credentials`, `service-account*.json`, `*.tfvars`, `*.tfvars.json`, `kubeconfig*`, and every
  pattern now ignores case (`Keys/`, `ID_RSA`). Two are narrower: `keys/` and `credentials*` no
  longer hide source code (`src/auth/credentials.py`, `src/keys/bindings.ts` were refused with exit
  2); data files under those names stay refused. Files that become readable are new units for
  `check` (`NOT_LISTED`) in a code map whose scope covers them.
- `search` ranks the code a test method leads to above the test itself: a test's own score counts
  0.4 (was 0.5, the same share it lends to that code, so a test whose name held every query word
  came first). Eval numbers in `docs/pilots.md`.
- The command modules are imported from a written-out list, so `impact` shows
  `commands/__init__.py` as the importer of each command and `tests-for` follows it. No change to
  the CLI.
- `tools/eval_nav.py` runs the tasks about this repository on a pinned snapshot (`snapshot` in
  `tools/eval/tasks.toml`, exported with `git archive`, without `tools/eval/`) instead of the
  checkout, which changed under the tasks with every commit; `--repo DIR` runs on a directory as
  it is. A `locate` gold must still contain the message it is asked about (two had gone stale when
  the code moved, and counted as misses). `--fail-under MRR` is the floor CI enforces.
- CI runs the eval on the snapshot, and builds the wheel, installs it and runs it. mypy checks 25
  modules instead of 4 (every one that passes `disallow_untyped_defs`).
- Removed `Graph.pagerank`, which nothing called (`map` ranks with `ranking.pagerank_files`).
- The test harness writes the throwaway repos' git settings directly and removes its cache
  directory at exit: the suite takes about a third less time.

## [0.2.0] - 2026-10-07

### Added

- `outline` takes several files or directories (their git code files, recursively): top-level
  declarations by default, within `--tokens` (default 2000) with a count of the files left out.
  The JSON is then `{"files": [...]}`; a single file keeps its shape.
- `symbol --skeleton`: every declaration of a class (or other symbol) with the bodies of its
  innermost members replaced by `… (lines A-B)`; a Python docstring keeps its first line and a
  closing brace stays. JSON: `skeleton` and `elided`.
- `search <keywords>`: BM25 over symbol names (split at case changes and underscores, lightly
  stemmed), containers, signatures, doc summaries and paths, plus each file's header and code-map
  row. A test method whose name matches lends its score to the production code its body uses
  (`via`). Production code ranks above tests and code above Markdown and data files; ties break
  on path and line. Capped by `--limit` (default 15) or `--tokens` with a count of what was left
  out, filtered by `--area`. The index is cached with the analysis cache (packed arrays: a warm
  search on a 3,000-file repo loads it in well under a second).
- `locate "<message>"` finds the code that printed a message: overlapping word runs looked up
  literally (interpolated values and strings split across lines still match), weighted by rarity,
  summed per enclosing symbol, production code before tests before docs; `--regex` for a pattern.
  `locate --trace [FILE|-]` reads Python, Node/V8, Firefox/Safari, Java/Kotlin, C#, Dart, Go and
  Rust traces and generic `path:line`, maps each frame to a repo file by the longest shared path
  suffix (a bare file name lists every candidate) and lists the in-repo frames innermost first with
  their enclosing symbol; the rest are `skipped`.
- `impact <file>` lists `importers`: the files whose Python or JS/TS import statements resolve to
  it (relative and absolute Python modules, `src/` layouts, JS/TS relative paths with `.js` written
  for `.ts`, `index` files, `@/`, `~/` and `#/` aliases). Import edges are kept apart from fan-in,
  so `check`, `sync` and the edge stamps are unaffected.
- `brief <file|Name>`: one answer before an edit within `--tokens` (default 1500): area row and
  review stamp, exported outline (two levels), fan-in, callers one hop away ranked by how much of
  the target they use (or by reference sites for a name), the tests `tests-for` picks and the
  runner command, docs that mention it. Over budget the outline's tail goes first, then docs, then
  the caller and test lists; each cut leaves a count. JSON `related` lists the callers then the
  tests as shown.
- `syntax [paths | --diff]`: do the edited files still parse? Python with `ast.parse`, JSON with
  `json.loads` (JSON with comments and trailing commas passes), TOML with `tomllib`; JS/TS, C#,
  Java, Kotlin, Swift, Dart, Go, Rust and C-family files get a bracket-balance check on masked text,
  reported only when the HEAD version was balanced. `path:line:col: lang: message`, exit 1 on
  findings; JSON `preexisting` marks errors HEAD already had. `topomark.syntax.check_file(ctx,
  path)` needs no index, for hooks.
- `tests-for` follows a changed file that no test mentions to its callers, up to `--depth N` hops
  (default 2, `0` for the old behaviour): import statements transitively, name references one
  hop. Test files that import a reached caller are selected whole, tests that mention its
  distinctive names by method; each such test says `via` which callers it came through.
  Barrels and test helpers cost no hop. More than 30 callers stops the search (`limited`).
- `[[tests.runner]]` takes an optional `suite` command; `tests-for` prints it (`suite_commands`)
  when a changed file stays uncovered, and lists files that import modules by computed names
  (`dynamic_loaders`) as a "may miss tests" warning.
- `changes [--staged | --since REV]`: the diff's `git diff -U0` line ranges mapped to the
  innermost declaration on each side (the old side analyzed from `git show REV:path`), classified
  by qualified name as `added`, `removed`, `signature` (interface) or `body`; a changed header
  comment counts as interface. For removed and re-signed names, the references left (callers and
  tests); then the tests to run with runner commands, and the code-map rows to review with their
  stamp state.
- Claude Code plugin hooks (`hooks/hooks.json`) and `agent-hook session-start|pre-read|post-edit`,
  the command they run. At session start: the L0 path, each area's name and file, one line of
  navigation commands and whether review stamps exist (at most 40 lines and 4 KB; without a code
  map, one line suggesting `map`). Before a Read: for a file over 400 lines, a pointer to `outline`
  and `symbol --skeleton`; for the first file read in an area, its area file; each hint once per
  session, nothing for ranged reads. After an Edit, Write or MultiEdit: the `syntax` check of that
  file, reported only when the edit broke it. The output follows the hook protocol, not the `--json`
  envelope; the command exits 0 whatever happens and never makes a permission decision.

### Changed

- `_generated/fanin.md` is titled "Fan-in" (was "C# / code fan-in"); `check` reports the generated
  file as stale until `topomark gen` runs once.
- `outline`'s positional argument is now `paths` (was `file`), visible in `capabilities --json`;
  one path keeps the old output shape.
- `locate` and `search` exit 0 with an empty list when nothing matches (`find` still exits 4);
  `changes` always exits 0.
- `refs` text output shows every group's counts and the first 20 sites (`--limit N` for more); the
  JSON still lists up to `--limit`, default 200. `impact` says `--top N` where it cuts a list.
- `find` sorts code before Markdown headings and data-file keys, after exactness and before the
  production/test split, so `find stamp` lists `Stamps` ahead of the docs that talk about stamps.
- Warm `map`, `impact` and `tests-for` on a 3,000-file repo take 30 to 55 % less CPU, and single-file
  `outline`/`symbol` no longer grow with the repo (numbers in `docs/pilots.md`). Glob lists compile into
  one matcher; the analysis cache is 256 `marshal` shards with symbols decoded on first use (cache
  format 2: the first run after upgrading re-parses, and the old `index.json` is deleted); graph
  tables, identifier counts, import edges and the search index are cached under a digest of every
  file's cache key, the config and the code that builds them. Results are unchanged.
- Start-up does less: `importlib.metadata` is imported only when the version cannot be read from
  `pyproject.toml`, `traceback` only when one is printed, and the command modules no longer import
  the workspace (and with it the index) when the parser is built. This matters most for the hooks,
  which start a process per tool call; `agent-hook` also reads at most 1 MB of payload (a larger
  one, such as a huge Write, gets no answer).
- The exit-code contract lists `doctor` (a failing check) and `syntax` (a file that no longer
  parses) under exit 1, findings, next to `check` and `stale`.
- `symbol --skeleton --signature` is a usage error (exit 2): the two are alternatives.
- `map` stops ranking files once the rest cannot reach the list it shows: the same output, less
  work on a big repo.

### Removed

- **Breaking:** topomark writes English only. The Traditional Chinese templates, `init --lang` and
  the `[topomark] lang` key are gone; a `topomark.toml` that still sets `lang` is a `CONFIG` error
  (exit 3) until the line is deleted, and `init` no longer writes it. The Chinese formats are no
  longer parsed: `check` and `sync` read only `fan-in P/T` and `draft --write` finds only the
  English file-table headings (`## Files`, `## File table`, `## Units`, `## Files and units`), so
  a repo with a zh-Hant code map must rewrite its rows by hand: `扇入 P／T` → `fan-in P/T`,
  `` `dir/`（N 檔） `` → `` `dir/` (N files) ``, and rename the file-table heading. `init --json`
  still reports `"lang"`, now always `"en"`.
- The package no longer ships `topomark/templates/en/` and `topomark/templates/zh-Hant/`: the `init`
  templates are `topomark/templates/*.md`.

### Fixed

- The `[[tests.runner]]` example in the README and `docs/config.md` paired `python3 -m unittest {names}`
  with `names = "class"`, which prints bare class names unittest cannot run; it now uses
  `names = "file"`, and `docs/config.md` says which runners take bare class names.
- `tests-for` merged a second selection from the same test file into a narrower one: whole
  classes picked for one changed file could shrink to the methods picked for another. The broader
  selection now wins.
- The README, `docs/concepts.md` and the skill's command reference listed only the first adapters;
  the Dart, Kotlin, Swift, Go, Rust and C/C++/Objective-C adapters that 0.1.0 already shipped are
  now listed too.
- JSON, TOML and YAML files counted as code (the data adapter reports `json`/`toml`/`yaml`, not
  `data`): `map` listed manifest keys among the most central code, and `tests-for` searched tests
  for the keys of a changed data file.
- Secrets could be read through a symbolic link: a tracked `link.py -> .env`, or a link to a file
  outside the repository, was indexed and shown by `search`, `find` and `locate`. Such links are
  left out of the file list, and reading refuses them. A secret-looking file over the 3 MB parse
  limit was read to hash it; it is refused before anything is read.
- Paths outside the repository were read: `outline ../other/x.py`, an absolute path elsewhere,
  `symbol ../x.py#f`, `syntax` and `impact` with such a path. They are NOT_FOUND (exit 4) in every
  command that takes a path. A repo-relative `./.github/ci.yml` (with `-C`, from another directory)
  lost its leading dot and became `github/ci.yml`.
- File names git quotes (non-ASCII, unusual characters) were reported deleted by `tests-for` and
  `changes`, and `syntax` skipped them; changed files are read NUL-separated from git now.
- Runner commands: the clean-up after an empty `{class}` or `{method}` rewrote unrelated text
  (`go test ./... -run` became `go test ./ -run`, `cd . &&` became `cd  &&`); only the separator
  next to the empty placeholder goes now. Test paths are quoted for a POSIX shell, so a file name
  with a space or `$(...)` is one literal argument; plain paths and names print as before.
- A repo package named like a standard-library module (`calendar/slots.py`) was never the target of
  an import; it is now when the importer can reach it before the standard library (`import json`
  in `src/app.py` still never means `tools/json.py`).
- `tests-for --since REV` ignored a revision git does not know and listed nothing changed; it is
  NOT_FOUND (exit 4), as in `changes`.
- `search` failed with exit 7 when a symbol's name held a tab or a newline (a Markdown heading
  `## Alpha<tab>beta`).
- `tests-for` picked test support code (a shared `tests/harness.py` that mentions the changed names)
  as the test to run, and stopped there. Only runnable test files are picked now, and a changed
  helper leads to the tests that use it.
- `changes` reported a file whose path holds a space as wholly added, and a mode change, a binary
  file or an empty file added or deleted as added with every symbol an interface change. Each file
  is read from its `diff --git` header now, and a removed line starting with `-- ` is no longer
  taken for a file header.
- `locate --trace` could take seconds on one long line (7.7 s for 4,000 characters): the generic
  `path:line` pattern backtracked. It runs in linear time now, over the first 500 characters of a
  line.
- `syntax` and the post-edit hook flagged code that is valid for a newer Python than the one running
  topomark (`except A, B:` under 3.12, PEP 695 under 3.11). A Python finding names the interpreter
  that checked it, and the project's `requires-python` when its minimum is newer; the hook stays
  quiet then. Swift raw strings (`#"…"#`) and `#/…/#` regex literals no longer cause false bracket
  findings.
- `locate` counted how rare a word run is across every file, so tests and docs quoting a message
  verbatim could push the production code that printed it out of the results. Rarity is now counted
  among production files for production places.
- The installed pre-commit script's comment said it ran only when the commit touched code or the
  code map; it runs on any commit with staged changes, and only findings block it.

### Development

- `tools/eval_nav.py` (gold ranks, hit@1/@5 and output tokens per navigation task, `--compare REV`),
  `tools/bench_nav.py` (warm timings of each command and hook) and `tools/synth_repo.py` (the
  deterministic multi-language repo they run on). topomark maps itself in `docs/codemap/`, and CI
  runs `topomark check` on that code map.
- `eval_nav.py --compare REV` drops the config keys an older REV rejects instead of scoring every
  task as a miss; errors are reported apart from misses; `expect = "miss"` tasks are controls.
  `bench_nav.py` fails a hook case whose output is wrong. `synth_repo.py` and the test harness no
  longer run the developer's git hooks and no longer need git 2.28 (`init -b`).

## [0.1.0] - 2026-10-05

### Added

- Navigation commands that work in any git repository: `outline`, `symbol`, `find`, `refs`,
  `impact`, `tests-for` and `map` (a ranked repo map within a token budget).
- Language adapters for C#, Java, JavaScript/TypeScript, Python, shell, SQL, data files (JSON,
  JSONC, TOML, YAML, asmdef) and Markdown, with a plain-text fallback; per-file analysis cache
  outside the repository.
- The code-map doc system: L0 index and L1 area files with frontmatter ownership (`scope`,
  `granularity`, `depth`), `check` (coverage, dead paths, ownership conflicts, line caps, fan-in,
  generated reports, unit counts), `gen`, `sync`, `owner`.
- Review stamps: per-unit interface hashes and content blobs in `stamps.json`; `stamp`, `diff`,
  `stale`; cross-area edge stamps per area.
- `init`: detects languages and project manifests, proposes areas from manifest directories,
  chooses file or directory granularity, suggests excludes for generated code, links existing rule
  files, writes `topomark.toml` and the code-map skeleton in English or Traditional Chinese;
  `--dry-run` writes nothing.
- `draft`: the rows an area file is missing, with summaries from header comments and docstrings and
  the current fan-in; `--write` appends them under the area's file table.
- `hook install|uninstall|status` (opt-in pre-commit gate), `doctor`, `capabilities`.
- Global `--json` with `schema_version`, stable exit codes 0 to 7, `-C/--repo`, `--config`.
- Agent skill `skills/topomark`, Claude Code plugin and marketplace manifests, Codex plugin manifest.
- CI: ruff, mypy, unittest on Linux and Windows, CLI smoke, manifest and skill gates.

[Unreleased]: https://github.com/tipoLi5890/topomark/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/tipoLi5890/topomark/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/tipoLi5890/topomark/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/tipoLi5890/topomark/releases/tag/v0.1.0
