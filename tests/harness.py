"""Shared test helpers: run the CLI in-process, build throwaway git repos.

Every test run gets its own cache directory (``TOPOMARK_CACHE``, always set, even when
the developer's shell exports one) so tests never touch the user's cache, and repos are
created under a temporary directory with a local git identity.
"""

from __future__ import annotations

import atexit
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ["TOPOMARK_CACHE"] = tempfile.mkdtemp(prefix="topomark-test-cache-")
atexit.register(shutil.rmtree, os.environ["TOPOMARK_CACHE"], ignore_errors=True)

from topomark.cli import main  # noqa: E402


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = main(list(argv))
        except SystemExit as e:  # argparse --help / usage errors
            rc = int(e.code or 0)
    return rc, out.getvalue(), err.getvalue()


def json_of(argv: list[str], expect: int | None = 0) -> dict:
    rc, out, err = run_cli([*argv, "--json"])
    if expect is not None and rc != expect:
        raise AssertionError(f"exit {rc} != {expect} for {argv}\nstdout: {out}\nstderr: {err}")
    return json.loads(out)


class TempRepo:
    """A git work tree in a temp dir. ``write`` takes {path: text}; text is dedented."""

    def __init__(self, files: dict[str, str] | None = None, commit: bool = True) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="topomark-repo-")
        self.root = Path(self._tmp.name).resolve()
        self.git("init", "-q")
        # Written straight into .git instead of five more git processes per repo (most of a test run is
        # git start-up). HEAD on main: `init -b` needs git 2.28. A global core.hooksPath (the developer's
        # own hooks) must not apply to throwaway repos: pin the repo's own hooks dir, which the
        # `hook install` tests write into.
        dot_git = self.root / ".git"
        with open(dot_git / "HEAD", "w", encoding="utf-8", newline="\n") as fh:
            fh.write("ref: refs/heads/main\n")
        with open(dot_git / "config", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f'[core]\n\thooksPath = "{(dot_git / "hooks").as_posix()}"\n'
                     '[user]\n\tname = Test\n\temail = test@example.invalid\n'
                     '[commit]\n\tgpgsign = false\n')
        if files:
            self.write(files)
            if commit:
                self.commit("init")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                              encoding="utf-8", check=True).stdout

    def write(self, files: dict[str, str]) -> None:
        for path, text in files.items():
            full = self.root / path
            full.parent.mkdir(parents=True, exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(textwrap.dedent(text).lstrip("\n"))

    def read(self, path: str) -> str:
        with open(self.root / path, encoding="utf-8") as fh:
            return fh.read()

    def commit(self, message: str = "commit") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "--no-verify", "-m", message, "--allow-empty")

    def cli(self, *argv: str) -> tuple[int, str, str]:
        return run_cli(["-C", str(self.root), *argv])

    def json(self, *argv: str, expect: int | None = 0) -> dict:
        return json_of(["-C", str(self.root), *argv], expect=expect)

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> "TempRepo":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
