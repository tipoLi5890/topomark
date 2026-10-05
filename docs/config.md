# Configuration reference: `topomark.toml`

`topomark.toml` lives at the repository root (or wherever `--config PATH` points). Every key is
optional; a repository without the file gets the defaults below. Unknown sections and keys are a
`CONFIG` error (exit 3), so a typo cannot silently do nothing.

Areas are **not** configured here. Each area file's frontmatter (`area`, `title`, `summary`,
`scope`, `granularity`, `depth`) is the single source of truth for ownership; see
[concepts.md](concepts.md).

```toml
[topomark]
docs_dir = "docs/codemap"   # where L0, area files, stamps.json and _generated/ live
lang = "en"                 # "en" or "zh-Hant": language of generated text and drafted rows
l0_max = 160                # line cap for <docs_dir>/README.md
l1_max = 260                # line cap for each area file
min_name = 5                # names shorter than this are ignored by fan-in and refs ranking

[files]
required_roots = []         # only files under these prefixes need a row (default: everywhere)
required_ext = [".py", ".ts"]   # extensions that need a row (default: the code list below)
every_file_roots = ["contracts/"]   # every file under these prefixes needs a row, any extension
exclude = ["**/l10n/app_localizations*.dart", ".claude/"]   # added to the built-in excludes
include_default_excludes = true     # false: use only `exclude`
keep_short_names = ["Id", "L10n"]   # short names that still count for fan-in
mention_roots = ["docs/"]   # where `impact` looks for docs that mention a path or name

[tests]
patterns = ["tests/", "*_test.go"]  # replaces the built-in test-file patterns

[[tests.runner]]
match = "tests/"            # path prefix or glob of the test files this runner handles
command = "python -m pytest {files}"
names = "file"              # what {names} joins: file | class | method
join = " "
max_names = 20              # above this, fall back to `fallback`
fallback = "file"           # class | file
```

## `[topomark]`

| Key | Default | Meaning |
|---|---|---|
| `docs_dir` | `docs/codemap` | Directory of the code map. Files under it never need rows. |
| `lang` | `en` | `en` or `zh-Hant`. Picks the generated-report strings, `init` templates and the fan-in word written by `draft` (`fan-in P/T` or `扇入 P／T`). |
| `l0_max` | `160` | Line cap of the L0 index (`LINE_CAP`). |
| `l1_max` | `260` | Line cap of each area file. |
| `min_name` | `5` | Declared names shorter than this are too ambiguous to count as references. |

## `[files]`

| Key | Default | Meaning |
|---|---|---|
| `required_roots` | everywhere | Path prefixes whose code files need a row. |
| `required_ext` | code extensions | Extensions that need a row: `.cs .java .kt .kts .swift .dart .go .rs .c .cc .cpp .h .hpp .m .mm .js .mjs .cjs .jsx .ts .tsx .py .sh .bash .ps1 .sql .gradle .asmdef .jsonc`. |
| `every_file_roots` | none | Prefixes where every file needs a row and is parsed (contracts, schemas). |
| `exclude` | none | Extra glob patterns, added to the built-in list. |
| `include_default_excludes` | `true` | Set `false` to replace the built-in list instead of extending it. |
| `keep_short_names` | none | Short names that still count (for example a class called `L10n`). |
| `mention_roots` | `["docs/"]` | Where `impact` searches for prose that mentions a path or name. |

Built-in excludes: `.git/`, `node_modules/`, `.venv*/`, `venv/`, `__pycache__/`, `build/`, `dist/`,
`.tipo-harness/`, `**/vendor/**`, `**/generated/**`, `*.generated.*`, `*.min.js`, `*.min.css`,
`**/archive/**`, `*.meta`, `.topomark/`.

Secret-looking paths are never read or listed, whatever the config says: `keys/`, `.ssh/`,
`ssh_config`, `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.keystore`, `*.jks`, `id_rsa*`,
`id_ed25519*`, `id_ecdsa*`, `credentials*`, `*.secret`, `*secret*.json`, `ssh-hosts.json`, `.netrc`,
`.npmrc`, `.pypirc`.

### Glob syntax

A small subset of gitignore:

- `name/` matches a directory named `name` at any depth; with an inner slash (`product/vendor/`)
  it is anchored at the repository root.
- A pattern without a slash (`*.g.dart`) matches the file name at any depth.
- A pattern with a slash is anchored at the root; `**` spans directories, `*` and `?` stay inside one
  path segment.

Files come from git (tracked plus untracked-but-not-ignored), so whatever `.gitignore` excludes is
already out.

## `[tests]`

`patterns` replaces the built-in test-file patterns (`tests/`, `test/`, `__tests__/`, `**/Tests/**`,
`test_*.py`, `*_test.py`, `*.test.ts(x)`, `*.test.js`, `*.test.mjs`, `*.spec.ts(x)`, `*.spec.js`,
`*Tests.cs`, `*Test.cs`, `*_test.dart`, `*Test.kt`, `*Tests.swift`, `*Test.java`, `*_test.go`).

`[[tests.runner]]` tables turn the tests `tests-for` selected into commands. The first runner whose
`match` (prefix or glob) fits a test file handles it. `command` placeholders:

| Placeholder | Becomes |
|---|---|
| `{files}` | the selected test files, joined by `join` |
| `{names}` | files, classes or methods (per `names`), joined by `join` |
| `{file}` `{class}` `{method}` | one command per item |

When `{names}` would exceed `max_names`, it falls back to `fallback` granularity.

```toml
[[tests.runner]]
match = "tests/"
command = "python3 -m unittest {names}"
names = "class"

[[tests.runner]]
match = "Assets/Tests/"
command = "Tools/run-tests.sh edit {names}"
names = "class"
join = " "
```
