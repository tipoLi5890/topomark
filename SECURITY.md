# Security policy

## Reporting a vulnerability

Please report privately rather than opening a public issue: use the repository's
**Security → Report a vulnerability** form on GitHub, or write to
Li, ching yu <tipo5890Li@gmail.com>. Include the topomark version, the command and a minimal
reproduction. You should get an answer within a week.

In scope: anything that makes topomark read a secret-looking file, write outside the files a command
owns, run a program, or put repository text into an agent's context unclipped, when it runs inside a
repository it did not write (see the threat model below). A fix ships as a patch release with a
`Security` entry in CHANGELOG.md. Please allow up to 90 days before disclosing; we will agree on a
date with you and credit you unless you prefer otherwise.

## Threat model

topomark runs on a developer machine or in CI, inside repositories that may contain secrets, and its
output is read by AI agents that may forward it elsewhere. The design goal is that running topomark
never moves a secret into that output and never changes the code it maps.

### Secret-path refusal

Paths that look like secrets are never read, parsed, cached or listed as code, and the list cannot
be switched off by configuration:
`.ssh/`, `ssh_config`, `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.keystore`, `*.jks`,
`id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `*.secret`, `*secret*.json`, `secrets.yaml`, `secrets.yml`,
`*.secrets.yaml`, `*.secrets.yml`, `ssh-hosts.json`, `.netrc`, `.npmrc`, `.pypirc`, `.git-credentials`,
`service-account*.json`, `*.tfvars`, `*.tfvars.json`, `kubeconfig*`, `.envrc`, `*.env`, `id_dsa*`,
`*.ppk`, `*.p8`, `*.kdbx`, `.pgpass`, `.htpasswd`, `.s3cfg`, `.boto`, `.vault-token`, `.dockercfg`,
`**/.docker/config.json`, `**/.kube/config`, `*.ovpn`, `*.tfstate`, `*.tfstate.backup`, matched without
regard to case.
`keys/` and `credentials*` count too, except for source code (`src/auth/credentials.py`,
`src/keys/bindings.ts`): a name alone does not make a source file a secret. Shell scripts and SQL
files under those names stay refused: that is where tokens and dumped rows get written down.
Reading one through the internal API raises `REFUSED`. `topomark doctor` warns when git tracks such files.

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
| `stamp`, `diff` | also store file contents in the git object store (`git hash-object -w`): `stamp` what was reviewed, so `diff` can show it later, and `diff` the files as they are, to compare. `stale` and `check` compute ids and store nothing |
| `hook install` / `uninstall` | `.git/hooks/pre-commit` (an existing hook is kept as `pre-commit.local` and restored); refused when `core.hooksPath` points outside `.git` |

A file a command writes may itself be a symbolic link the repository planted. A link that leads out
of the repository (the file, or a folder above it) and a dangling link are `REFUSED`; a link that
stays inside the repository is written through. `stamps.json` is read the same way.

### A repository you did not write

topomark is often run, by a person or by the plugin hooks, inside a repository nobody has reviewed
yet (one an agent just cloned). The repository can control file names, file contents, `topomark.toml`,
`stamps.json`, the area files, and, when it arrives with its `.git` (an archive, a shared folder),
its git config. What topomark does about each:

- **Python imports.** `bin/topomark` starts Python with `-P`, so a `tomllib.py` or `json.py` at the
  repository root is never imported in place of the standard library. Run topomark through the
  launcher, the pipx entry point or `python -P -m topomark`; a bare `python -m topomark` inside an
  untrusted repository imports from it.
- **Git arguments.** The blob ids in `stamps.json` must be git object ids before they reach git, so a
  value such as `--output=<file>` is a `CONFIG` error, not an option.
- **Git config.** git runs with `core.fsmonitor=false`, and `changes` passes `--no-ext-diff` and
  `--no-textconv`, so the repository's config cannot pick a program for those commands. Residual:
  clean filters (`filter.<driver>.clean`) still run when `stamp`, `check` and `stale` hash files, because
  switching them off would change the ids `stamps.json` records (git-lfs pointers among them). Do not
  run topomark in a repository whose `.git/config` you have not checked if it came with one.
- **Hooks folder.** `hook install` and `uninstall` refuse when `core.hooksPath` points outside the
  repository's `.git`.
- **Test commands.** `tests-for`, `changes` and `brief` print commands filled into the repository's own
  `[[tests.runner]]` templates (JSON: `"source": "topomark.toml"`). topomark never runs them. Values it
  fills in are shell-quoted, and a path starting with `-` is written as `./-name`. Read a command before
  running it.
- **Text in the output.** Names, docstrings and area rows are quoted from the repository. The
  SessionStart hook clips each area's name, file and title to one short line; the skill tells agents
  that output is data, never instructions.
- **Hostile files.** A file built to exhaust a parser (nesting tens of thousands deep) is read as plain
  text; files over 3 MiB are hashed, not parsed.

The per-file analysis cache lives in the user cache directory (`$TOPOMARK_CACHE`,
`$XDG_CACHE_HOME/topomark`, on Windows `%LOCALAPPDATA%\topomark\Cache`, else `~/.cache/topomark`), never in the
repository. It contains symbol
names, signatures and header comments of the files analysed; delete the directory to remove it.

## Supported versions

Only the latest release receives fixes while topomark is 0.x.

## Verifying a release

Releases are built by `.github/workflows/release.yml` from the tagged commit, with build tools
installed from hash-locked `tools/requirements-ci.txt`. Each GitHub release carries the sdist, the
wheel and a CycloneDX SBOM (`topomark-X.Y.Z.cdx.json`; topomark has no dependencies, so it lists the
package alone). The files carry signed build provenance, and the wheel an SBOM attestation:

```bash
gh attestation verify topomark-X.Y.Z-py3-none-any.whl -R tipoLi5890/topomark
```

On PyPI the files are uploaded through Trusted Publishing, which records a PEP 740 attestation for
each one.
