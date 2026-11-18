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

Symbolic links are followed only inside the repository: ``git_files`` leaves out a link
that resolves outside the root, onto a secret-looking path or onto something that is not a
file, and ``read_text`` refuses the same, so a tracked ``notes.py -> ../.ssh/id_rsa`` or
``link.py -> .env`` is never read. Only paths that pass through a link are resolved
(``os.path.realpath`` costs a system call per path component).
"""

from __future__ import annotations

import functools
import os
import re
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from .errors import TopomarkError

# Matched against the lower-cased path, so `Keys/` and `ID_RSA` are caught too.
SECRET_PATTERNS: tuple[str, ...] = (
    ".ssh/", "ssh_config", ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "*.keystore", "*.jks", "id_rsa*", "id_ed25519*", "id_ecdsa*", "*.secret",
    "*secret*.json", "secrets.yaml", "secrets.yml", "*.secrets.yaml", "*.secrets.yml", "ssh-hosts.json",
    ".netrc", ".npmrc", ".pypirc", ".git-credentials", "service-account*.json", "*.tfvars", "*.tfvars.json",
    "kubeconfig*",
    # environment files under other names, keys, password stores and tool credentials
    ".envrc", "*.env", "id_dsa*", "*.ppk", "*.p8", "*.kdbx", ".pgpass", ".htpasswd", ".s3cfg", ".boto",
    ".vault-token", ".dockercfg", "**/.docker/config.json", "**/.kube/config", "*.ovpn", "*.tfstate",
    "*.tfstate.backup",
)
# Names that say "secret" about a data file but are ordinary names for source code
# (`src/auth/credentials.py`, `src/keys/bindings.ts`): secret unless the file is source code.
SECRET_NAME_PATTERNS: tuple[str, ...] = ("keys/", "credentials*")
SOURCE_EXT: tuple[str, ...] = (
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".cs", ".java", ".kt", ".kts",
    ".swift", ".dart", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h++",
    ".inl", ".m", ".mm",
)
# Left out on purpose, though they have adapters: shell scripts and SQL (`keys/deploy.sh`,
# `credentials.sql`) are where tokens and dumped rows are written down, so those names stay refused.

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git/", "node_modules/", ".venv*/", "venv/", "__pycache__/", "build/", "dist/",
    "**/vendor/**", "**/generated/**", "*.generated.*", "*.min.js", "*.min.css",
    "**/archive/**", "*.meta", ".topomark/",
)


def _glob_body(pattern: str, segment: bool = False) -> str:
    """Regex body for a glob. ``segment``: the text is one path segment, so ``**`` is ``*``."""
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i) and not segment:
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append("[^/]*" if segment else ".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


@functools.lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    return re.compile("^" + _glob_body(pattern) + "$")


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


def _alternation(bodies: list[str], head: str, tail: str) -> re.Pattern[str] | None:
    return re.compile(head + "(?:" + "|".join(bodies) + ")" + tail) if bodies else None


@functools.lru_cache(maxsize=256)
def _matcher(patterns: tuple[str, ...]) -> Callable[[str], bool]:
    """``matches`` for a whole pattern list: at most four regex calls per path, whatever its length."""
    base: list[str] = []
    full: list[str] = []
    seg_dir: list[str] = []
    anchored_dir: list[str] = []
    for p in patterns:
        if p.endswith("/"):
            d = p[:-1]
            if "/" in d:
                anchored_dir.append(_glob_body(d))
            else:
                seg_dir.append(_glob_body(d, segment=True))
        elif "/" not in p:
            base.append(_glob_body(p))
        else:
            full.append(_glob_body(p.lstrip("/")))
    rx_base = _alternation(base, "^", "$")
    rx_full = _alternation(full, "^", "$")
    rx_seg = _alternation(seg_dir, "(?:^|/)", "/")  # a directory segment: never the file name
    rx_dir = _alternation(anchored_dir, "^", "/")   # an anchored directory prefix

    def match(path: str) -> bool:
        return bool((rx_base is not None and rx_base.match(path.rsplit("/", 1)[-1]))
                    or (rx_full is not None and rx_full.match(path))
                    or (rx_seg is not None and rx_seg.search(path))
                    or (rx_dir is not None and rx_dir.match(path)))

    return match


def matches_any(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return _matcher(tuple(patterns))(path)


def is_secret(path: str) -> bool:
    low = path.lower()
    if matches_any(low, SECRET_PATTERNS):
        return True
    return matches_any(low, SECRET_NAME_PATTERNS) and not low.endswith(SOURCE_EXT)


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
    """Run git in ``root``. ``core.fsmonitor`` in a repository's own .git/config names a program git
    starts while it refreshes the index (``ls-files``, ``diff``); a repository handed over with its
    .git (an archive, a shared folder) could run code through it, so it is switched off here.
    The direct ``cat-file`` calls in this module and stamps.py read objects only and never refresh
    the index. Clean filters still apply to ``hash-object`` (turning them off
    would change the ids stamps.json records, git-lfs pointers among them); SECURITY.md says so."""
    return subprocess.run(["git", "-C", str(root), "-c", "core.fsmonitor=false", *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", input=input_text, check=check).stdout


def git_objects(root: Path, specs: list[str]) -> dict[str, str | None]:
    """The text of several git objects (``HEAD:src/a.py``, ``:src/a.py`` for the index, a blob id)
    from one ``git cat-file --batch`` process; None for an object git does not have. Text is
    decoded as UTF-8 with CRLF read as LF, like ``read_text``."""
    plain = [s for s in specs if "\n" not in s]
    out: dict[str, str | None] = {s: None for s in specs}
    if plain:
        data = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], capture_output=True,
                              input=("\n".join(plain) + "\n").encode("utf-8"), check=False).stdout
        pos = 0
        for spec in plain:
            end = data.find(b"\n", pos)
            if end < 0:
                break
            head = data[pos:end].split()
            pos = end + 1
            if len(head) != 3 or not head[2].isdigit():
                continue  # "<spec> missing", or ambiguous: no content follows
            size = int(head[2])
            if head[1] == b"blob":
                out[spec] = data[pos:pos + size].decode("utf-8", errors="replace").replace("\r\n", "\n")
            pos += size + 1
    for spec in specs:
        if "\n" in spec:  # a newline in a path cannot be written on a batch line
            done = subprocess.run(["git", "-C", str(root), "cat-file", "blob", spec], capture_output=True, check=False)
            out[spec] = done.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n") if done.returncode == 0 else None
    return out


_PLAIN: dict[str, frozenset[str]] = {}  # root -> files git_files saw as regular files, no link on the way


def git_files(root: Path) -> list[str]:
    """Tracked plus untracked-not-ignored files that exist on disk, POSIX paths, sorted.
    A path through a symbolic link (the file or a folder on the way) stays only when it
    resolves to a file inside the repository that does not look secret (a secret-looking
    name itself stays: it is listed, never read). The rest are remembered as plain files,
    which ``safe_path`` then opens without another system call."""
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    seen = set()
    out = []
    plain = set()
    for f in listed:
        if not f or f in seen:
            continue
        seen.add(f)
        try:
            mode = os.lstat(root / f).st_mode
        except OSError:
            continue
        if stat.S_ISLNK(mode) or _dir_has_link(str(root), f.rpartition("/")[0]):
            if not is_secret(f):
                target = link_target(root, f)
                if target is None or is_secret(target) or not (root / target).is_file():
                    continue
        elif stat.S_ISREG(mode):
            plain.add(f)
        else:
            continue
        out.append(f)
    out.sort()
    _PLAIN[str(root)] = frozenset(plain)
    return out


@functools.lru_cache(maxsize=64)
def _real_root(root: str) -> str:
    return os.path.realpath(root)


@functools.lru_cache(maxsize=8192)
def _dir_has_link(root: str, d: str) -> bool:
    """Whether a directory on the way to ``d`` (repo-relative, "" for the root) is a symbolic link."""
    if not d:
        return False
    parent = d.rpartition("/")[0]
    return _dir_has_link(root, parent) or os.path.islink(os.path.join(root, d))


def _outside(path: str) -> bool:
    """A path that names no file inside the repository: absolute, on a drive, or climbing with ``..``."""
    p = path.replace("\\", "/")
    return p.startswith("/") or (os.name == "nt" and bool(re.match(r"[A-Za-z]:", p))) or ".." in p.split("/")


def _through_link(root: Path, path: str) -> bool:
    return os.path.islink(root / path) or _dir_has_link(str(root), path.replace("\\", "/").rpartition("/")[0])


def link_target(root: Path, path: str) -> str | None:
    """Where ``path`` really is, repo-relative POSIX after symbolic links, or None outside the repository."""
    real = os.path.realpath(root / path)
    base = _real_root(str(root))
    if real != base and not real.startswith(base.rstrip(os.sep) + os.sep):
        return None
    return Path(os.path.relpath(real, base)).as_posix()


def inside(root: Path, path: str) -> bool:
    """True if repo-relative ``path`` stays inside the repository, symbolic links followed."""
    if _outside(path):
        return False
    return not _through_link(root, path) or link_target(root, path) is not None


def safe_path(root: Path, path: str) -> Path:
    """The file to open for repo-relative ``path``: REFUSED when the name looks secret, when the
    path leaves the repository, or when a symbolic link on the way leads out of it or onto a
    secret-looking file."""
    if is_secret(path):
        raise TopomarkError("REFUSED", f"refusing to read a secret-looking file: {path}")
    if _outside(path):
        raise TopomarkError("REFUSED", f"refusing to read outside the repository: {path}")
    if path in _PLAIN.get(str(root), ()) or not _through_link(root, path):
        return root / path
    target = link_target(root, path)
    if target is None:
        raise TopomarkError("REFUSED", f"refusing to follow a symbolic link out of the repository: {path}")
    if is_secret(target):
        raise TopomarkError("REFUSED", f"refusing to read a secret-looking file: {path} -> {target}")
    return root / target


def read_text(root: Path, path: str) -> str:
    with open(safe_path(root, path), encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def user_path(root: Path, raw: str) -> str:
    """A user-supplied path → repo-relative POSIX path.

    An absolute path, or a relative one that exists from the current directory, is resolved
    and must lie inside the repository. Any other relative path is taken as repo-relative
    (what ``-C`` callers mean): ``./`` prefixes and ``a/../b`` are normalised, a trailing ``/``
    is kept. A path that leads out of the repository is NOT_FOUND."""
    import posixpath

    def outside() -> TopomarkError:
        return TopomarkError("NOT_FOUND", f"{raw} is outside the repository ({root})")

    p = Path(raw)
    if p.is_absolute() or os.path.exists(raw):
        try:
            return Path(os.path.abspath(raw)).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            if p.is_absolute():
                raise outside() from None
            # outside when read from the current directory: maybe repo-relative (with -C)
    s = raw.replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if not s:
        return s
    norm = posixpath.normpath(s)
    if norm == ".." or norm.startswith(("../", "/")):
        raise outside()
    return norm + "/" if s.endswith("/") and norm != "." else norm


def outside(path: str) -> bool:
    """True if repo-relative ``path`` names nothing inside the repository (absolute, or climbing with ``..``)."""
    return _outside(path)


def write_text(root: Path, path: str, text: str) -> None:
    """Write a file the command owns. The repository is not trusted: a symbolic link on the way (the
    file itself, or a folder above it) that leads out of it is REFUSED, and so is a dangling link,
    because ``mkdir`` and ``open`` would follow either and write somewhere else."""
    if _outside(path):
        raise TopomarkError("REFUSED", f"refusing to write outside the repository: {path}")
    full = root / path
    if link_target(root, path) is None:
        raise TopomarkError("REFUSED", f"refusing to write through a symbolic link out of the repository: {path}")
    if os.path.islink(full) and not os.path.exists(full):
        raise TopomarkError("REFUSED", f"refusing to write through a dangling symbolic link: {path}")
    full.parent.mkdir(parents=True, exist_ok=True)
    if full.is_symlink():  # a link inside the repository: write through it; replacing would put a file in its place
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return
    # the whole file or none of it: a run that is killed half way must not leave a cut-off
    # stamps.json or area file behind
    tmp = full.with_name(f".{full.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        if full.exists():
            os.chmod(tmp, stat.S_IMODE(full.stat().st_mode))
        os.replace(tmp, full)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
