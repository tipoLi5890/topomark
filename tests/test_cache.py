"""The fast paths give the same answers as the slow ones: cache entries decode to the
FileInfo the adapter produced, a single-file command reads one shard, whole-repo tables
cached under a digest follow file and config edits, caches of older formats are removed,
and the compiled glob matcher agrees with matching one pattern at a time."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.harness import TempRepo

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lang"


class CachedInfoTest(unittest.TestCase):
    def test_round_trip_matches_the_adapter(self) -> None:
        from topomark.graph import partial_names
        from topomark.index import CachedInfo, _pack
        from topomark.lang.registry import analyze

        files = sorted(p for p in FIXTURES.rglob("*") if p.is_file())
        self.assertGreater(len(files), 15)
        for f in files:
            rel = f.relative_to(FIXTURES).as_posix()
            with self.subTest(file=rel):
                with open(f, encoding="utf-8") as fh:
                    fresh = analyze(rel, fh.read())
                cached = CachedInfo(rel, _pack(fresh))
                self.assertEqual(cached.to_json(), fresh.to_json())
                self.assertEqual(cached.symbols, fresh.symbols)
                self.assertEqual((cached.idents, cached.surface, cached.imports),
                                 (fresh.idents, fresh.surface, fresh.imports))
                self.assertEqual(partial_names(cached), partial_names(fresh))


def _ctx(root: Path):
    from topomark.context import Context

    return Context(argparse.Namespace(repo=str(root), config=None, verbose=0, quiet=True))


class IndexTest(unittest.TestCase):
    def test_one_shard_per_file_and_old_caches_removed(self) -> None:
        from topomark.index import CachedInfo, Index, cache_dir

        files = {f"pkg/m{k:02d}.py": f"class Thing{k:02d}:\n    pass\n" for k in range(40)}
        with TempRepo(files) as repo:
            base = cache_dir(repo.root)
            (base / "index-0000000000000000").mkdir(parents=True)
            with open(base / "index.json", "w", encoding="utf-8", newline="\n") as fh:
                fh.write("{}")
            repo.json("map", "--tokens", "50")
            self.assertFalse((base / "index.json").exists())
            self.assertFalse((base / "index-0000000000000000").exists())
            idx = Index(_ctx(repo.root))
            info = idx.info("pkg/m07.py")
            self.assertIsInstance(info, CachedInfo)
            self.assertEqual([s.qualname for s in info.symbols], ["Thing07"])
            self.assertEqual(len(idx._shards), 1)  # outline/symbol never load the whole index


class DerivedCacheTest(unittest.TestCase):
    def fanin(self, repo: TempRepo, cache: str | None = None) -> dict:
        old = os.environ.get("TOPOMARK_CACHE")
        if cache:
            os.environ["TOPOMARK_CACHE"] = cache
        try:
            d = repo.json("impact", "src/alpha.py")
        finally:
            if old is not None:
                os.environ["TOPOMARK_CACHE"] = old
        return {"names": d["fanin_names"], "fanin": d["fanin"], "importers": d["importers"]}

    def test_follows_file_and_config_changes(self) -> None:
        files = {"src/alpha.py": "class Alpha:\n    pass\n",
                 "src/uses_alpha.py": "from alpha import Alpha\n\nX = Alpha()\n",
                 "src/other.py": "class Other:\n    pass\n"}
        with TempRepo(files) as repo, tempfile.TemporaryDirectory() as fresh:
            first = self.fanin(repo)
            self.assertEqual(first["fanin"]["prod_files"], ["src/uses_alpha.py"])
            self.assertEqual(self.fanin(repo), first)  # served from the derived cache
            repo.write({"src/other.py": "import alpha\n\nclass Other:\n    use = alpha.Alpha\n"})
            edited = self.fanin(repo)
            self.assertEqual(edited["fanin"]["prod_files"], ["src/other.py", "src/uses_alpha.py"])
            self.assertEqual(edited["importers"]["files"], ["src/other.py", "src/uses_alpha.py"])
            repo.write({"topomark.toml": "[topomark]\nmin_name = 6\n"})  # Alpha is now too short to count
            short = self.fanin(repo)
            self.assertEqual((short["names"], short["fanin"]["prod"]), ([], 0))
            self.assertEqual(short, self.fanin(repo, cache=fresh))  # same as computing from scratch


    def test_engine_code_is_part_of_the_key(self) -> None:
        from unittest import mock

        from topomark.index import Index

        with TempRepo({"src/alpha.py": "class Alpha:\n    pass\n"}) as repo:
            built: list[int] = []

            def build() -> int:
                built.append(1)
                return len(built)

            idx = Index(_ctx(repo.root))
            self.assertEqual(idx.derived("probe", "d", build), 1)
            self.assertEqual(idx.derived("probe", "d", build), 1)  # cached
            with mock.patch("topomark.index._derived_fingerprint", return_value="edited-engine"):
                self.assertEqual(idx.derived("probe", "d", build), 2)  # navigate.py & co. changed: rebuilt
            self.assertEqual(len(built), 2)


class HarnessCacheTest(unittest.TestCase):
    def test_tests_never_use_an_exported_cache(self) -> None:
        import sys

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as mine:
            env = dict(os.environ, TOPOMARK_CACHE=mine)
            out = subprocess.run([sys.executable, "-c", "import os, tests.harness; print(os.environ['TOPOMARK_CACHE'])"],
                                 cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", check=True)
            used = out.stdout.strip()
            self.assertNotEqual(used, mine)
            self.assertIn("topomark-test-cache-", used)
            os.rmdir(used)


class GlobMatcherTest(unittest.TestCase):
    def test_compiled_matcher_agrees_with_single_patterns(self) -> None:
        from topomark import repo
        from topomark.config import DEFAULT_TEST_PATTERNS

        root = Path(__file__).resolve().parents[1]
        tracked = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True,
                                 encoding="utf-8", check=True).stdout.split()
        paths = tracked + ["a/keys/x.pem", "keys/id", "x/.venv3/lib/a.py", "product/vendor/x/y.c",
                           "deep/product/vendor/z", "a/b/generated/c.ts", "src/x.generated.ts", "a.min.js",
                           ".env", "cfg/.env.local", "a/__tests__/x.js", "x/Tests/y/Z.cs", "a/b_test.go", "dist/x",
                           "x/dist", "node_modules/a/b.js", "abxb/c", "a/xb/c"]
        patterns = list(repo.SECRET_PATTERNS) + list(repo.DEFAULT_EXCLUDES) + list(DEFAULT_TEST_PATTERNS) + [
            "product/vendor/", "/abs/x.py", "src/**/*.py", "**/l10n/app*.dart", "a**b/", "tests/fixtures/**", "?.py"]
        single = {p: [repo.matches(p, pat) for pat in patterns] for p in paths}
        for k in range(1, len(patterns) + 1, 3):
            group = tuple(patterns[:k])
            bad = [p for p in paths if repo.matches_any(p, group) != any(single[p][:k])]
            self.assertEqual(bad, [], group[-1])


if __name__ == "__main__":
    unittest.main()
