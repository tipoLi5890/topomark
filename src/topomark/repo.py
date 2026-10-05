"""The repository as topomark sees it: git root, the file list, excludes, secrets.

Files come from git (tracked plus untracked-but-not-ignored), never from a raw
directory walk, so build output and caches that the repo already ignores stay out.

Glob semantics (a small subset of gitignore, documented in README):

* ``name/``      a directory named ``name`` at any depth (``keys/`` hits ``a/keys/x``);
  with an inner slash (``product/vendor/``) it is anchored at the repo root.
* ``*.ext``      a pattern without a slash matches the basename at any depth.
* ``a/**/b.py``  a pattern with a slash is anchored at the repo root; ``**`` spans
  directories, ``*`` and ``?`` stay inside one path segment.

Secret-looking paths are never read and never listed as code. The list is built
in and cannot be switched off; ``doctor`` reports secrets that git tracks.
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
from pathlib import Path

from .errors import TopomarkError

SECRET_PATTERNS: tuple[str, ...] = (
    "keys/", ".ssh/", "ssh_config", ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "*.keystore", "*.jks", "id_rsa*", "id_ed25519*", "id_ecdsa*", "credentials*", "*.secret",
    "*secret*.json", "ssh-hosts.json", ".netrc", ".npmrc", ".pypirc",
)

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git/", "node_modules/", ".venv*/", "venv/", "__pycache__/", "build/", "dist/",
    ".tipo-harness/", "**/vendor/**", "**/generated/**", "*.generated.*", "*.min.js",
    "*.min.css", "**/archive/**", "*.meta", ".topomark/",
)


@functools.lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(path: str, pattern: str) -> bool:
    """True if repo-relative POSIX ``path`` matches the gitignore-style ``pattern``."""
    if pattern.endswith("/"):
        d = pattern[:-1]
        if "/" in d:
            rx = _glob_regex(d)
            parts = path.split("/")
            return any(rx.match("/".join(parts[:k])) for k in range(1, len(parts)))
        rx = _glob_regex(d)
        return any(rx.match(seg) for seg in path.split("/")[:-1])
    if "/" not in pattern:
        return bool(_glob_regex(pattern).match(path.rsplit("/", 1)[-1]))
    return bool(_glob_regex(pattern.lstrip("/")).match(path))


def matches_any(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(matches(path, p) for p in patterns)


def is_secret(path: str) -> bool:
    return matches_any(path, SECRET_PATTERNS)


def find_root(start: str | os.PathLike[str] | None) -> Path:
    start_dir = Path(start or os.getcwd()).resolve()
    if not start_dir.exists():
        raise TopomarkError("NOT_FOUND", f"directory does not exist: {start_dir}")
    try:
        out = subprocess.run(["git", "-C", str(start_dir), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True, encoding="utf-8").stdout.strip()
    except FileNotFoundError as e:
        raise TopomarkError("NOT_GIT", "git is not installed or not on PATH") from e
    except subprocess.CalledProcessError as e:
        raise TopomarkError("NOT_GIT", f"not inside a git work tree: {start_dir}") from e
    return Path(out)


def git(root: Path, *args: str, input_text: str | None = None, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", input=input_text, check=check).stdout


def git_files(root: Path) -> list[str]:
    """Tracked plus untracked-not-ignored files that exist on disk, POSIX paths, sorted."""
    tracked = git(root, "ls-files", "-z").split("\0")
    others = git(root, "ls-files", "-z", "--others", "--exclude-standard").split("\0")
    seen = set()
    out = []
    for f in tracked + others:
        if f and f not in seen and (root / f).is_file():
            seen.add(f)
            out.append(f)
    out.sort()
    return out


def read_text(root: Path, path: str) -> str:
    if is_secret(path):
        raise TopomarkError("REFUSED", f"refusing to read a secret-looking file: {path}")
    with open(root / path, encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def write_text(root: Path, path: str, text: str) -> None:
    full = root / path
    full.parent.mkdir(parents=True, exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
