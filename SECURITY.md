# Security policy

## Reporting a vulnerability

Please report privately to Li, ching yu <tipo5890Li@gmail.com> rather than opening a public issue.
Include the topomark version, the command and a minimal reproduction. You should get an answer
within a week.

## Threat model

topomark runs on a developer machine or in CI, inside repositories that may contain secrets, and its
output is read by AI agents that may forward it elsewhere. The design goal is that running topomark
never moves a secret into that output and never changes the code it maps.

### Secret-path refusal

Paths that look like secrets are never read, parsed, cached or listed as code, and the list cannot
be switched off by configuration: `keys/`, `.ssh/`, `ssh_config`, `.env`, `.env.*`, `*.pem`, `*.key`,
`*.p12`, `*.pfx`, `*.keystore`, `*.jks`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `credentials*`,
`*.secret`, `*secret*.json`, `ssh-hosts.json`, `.netrc`, `.npmrc`, `.pypirc`. Reading one through
the internal API raises `REFUSED`. `topomark doctor` warns when git tracks such files.

Secrets inside ordinary source files (a hard-coded token) are not detected; topomark is not a
secret scanner. `outline` and `symbol` print constant values, so treat their output like the source.

### Offline

topomark makes no network requests. It runs `git` as a subprocess (`ls-files`, `rev-parse`,
`hash-object`, `cat-file`, `diff`) with argument lists, never through a shell.

### Writes

topomark is read-only on the repository except the files a command owns:

| Command | Writes |
|---|---|
| `init` | `topomark.toml` and files under `docs_dir`; refuses to overwrite without `--force`; `--dry-run` writes nothing |
| `draft --write`, `gen`, `sync`, `stamp` | files under `docs_dir` |
| `stamp` | also stores reviewed file contents in the git object store (`git hash-object -w`), so `diff` can show them later |
| `hook install` / `uninstall` | `.git/hooks/pre-commit` (an existing hook is kept as `pre-commit.local` and restored) |

The per-file analysis cache lives in the user cache directory (`$TOPOMARK_CACHE`,
`$XDG_CACHE_HOME/topomark` or `~/.cache/topomark`), never in the repository. It contains symbol
names, signatures and header comments of the files analysed; delete the directory to remove it.

## Supported versions

Only the latest release receives fixes while topomark is 0.x.
