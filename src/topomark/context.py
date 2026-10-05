"""Per-invocation context: repo root, config, file list. Everything is lazy so
``doctor`` and ``capabilities`` work in a repo with a broken config."""

from __future__ import annotations

import argparse
import sys
from functools import cached_property
from pathlib import Path

from . import repo
from .config import Config


class Context:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

    @cached_property
    def root(self) -> Path:
        return repo.find_root(getattr(self.args, "repo", None))

    @cached_property
    def config(self) -> Config:
        return Config.load(self.root, getattr(self.args, "config", None))

    @cached_property
    def all_files(self) -> list[str]:
        """Every git-visible file, before excludes (secrets included, never read)."""
        return repo.git_files(self.root)

    @cached_property
    def files(self) -> list[str]:
        """Files topomark works with: excludes and secrets removed."""
        ex = self.config.exclude
        return [f for f in self.all_files if not repo.is_secret(f) and not repo.matches_any(f, ex)]

    @cached_property
    def code_files(self) -> list[str]:
        """Files topomark parses: a language adapter exists, or the config names the extension,
        or the file sits under an every-file root. Images, audio and other binaries are skipped."""
        from .lang.registry import supported_extensions

        exts = tuple(set(supported_extensions()) | set(self.config.required_ext))
        every = tuple(self.config.every_file_roots)
        return [f for f in self.files if f.lower().endswith(exts) or (every and f.startswith(every))]

    def read(self, path: str) -> str:
        return repo.read_text(self.root, path)

    def log(self, message: str, level: int = 1) -> None:
        if getattr(self.args, "quiet", False):
            return
        if level <= max(1, getattr(self.args, "verbose", 0)):
            sys.stderr.write(message.rstrip("\n") + "\n")
