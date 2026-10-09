"""The fast paths give the same answers as the slow ones: cache entries decode to the
FileInfo the adapter produced, a single-file command reads one shard, whole-repo tables
cached under a digest follow file and config edits, caches of older formats are removed,
and the compiled glob matcher agrees with matching one pattern at a time."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
import time
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
    def test_incomplete_outline_warning_survives_the_cache(self) -> None:
        files = {"src/broken.py": "def ok(a,\n    return 1\n\n\ndef lost():\n    return 2\n", "src/fine.py": "def fine():\n    return 1\n"}
        with TempRepo(files) as repo:
            for _ in range(2):  # analyzed, then read back from the cache
                d = repo.json("outline", "src/broken.py")
                self.assertIn("a bracket opened on line 1 never closes", d["degraded"])
                rc, out, _ = repo.cli("outline", "src/broken.py")
                self.assertIn("  warning: this outline may be incomplete: a bracket opened on line 1", out)
                self.assertNotIn("degraded", repo.json("outline", "src/fine.py"))
            rc, out, _ = repo.cli("outline", "src")
            self.assertEqual(out.count("warning: this outline may be incomplete"), 1)

    def test_one_shard_per_file_and_old_caches_removed(self) -> None:
        from topomark.index import CachedInfo, Index, cache_dir

        files = {f"pkg/m{k:02d}.py": f"class Thing{k:02d}:\n    pass\n" for k in range(40)}
        with TempRepo(files) as repo:
            base = cache_dir(repo.root)
            unused, recent = base / "index-0000000000000000", base / "index-1111111111111111"
            gone_repo, live_repo, not_ours = (base.parent / n for n in ("a" * 16, "b" * 16, "c" * 16))
            for d in (unused, recent, gone_repo / "index-2222222222222222", live_repo / "index-3333333333333333",
                      not_ours / "index-4444444444444444", not_ours / "notes"):
                d.mkdir(parents=True)
            long_ago = time.time() - 200 * 86400
            for d in (unused, gone_repo / "index-2222222222222222", not_ours / "index-4444444444444444", not_ours / "notes"):
                os.utime(d, (long_ago, long_ago))
            with open(base / "index.json", "w", encoding="utf-8", newline="\n") as fh:
                fh.write("{}")
            repo.json("map", "--tokens", "50")
            self.assertFalse((base / "index.json").exists())
            self.assertFalse(unused.exists())     # another version's index, not used for months
            self.assertTrue(recent.exists())      # another version's index in use: two versions can alternate
            self.assertFalse(gone_repo.exists())  # a repository nobody has opened for months
            self.assertTrue(live_repo.exists())
            self.assertTrue(not_ours.exists())    # holds something this module did not put there
            for d in (recent, live_repo, not_ours):
                shutil.rmtree(d)
            idx = Index(_ctx(repo.root))
            info = idx.info("pkg/m07.py")
            self.assertIsInstance(info, CachedInfo)
            self.assertEqual([s.qualname for s in info.symbols], ["Thing07"])
            self.assertEqual(len(idx._shards), 1)  # outline/symbol never load the whole index


    def test_two_runs_at_once_keep_each_others_entries(self) -> None:
        from topomark.index import Index, shard_of

        names = [f"pkg/m{k:03d}.py" for k in range(600)]
        first = names[0]
        second = next(n for n in names[1:] if shard_of(n) == shard_of(first))
        files = {first: "class One:\n    pass\n", second: "class Two:\n    pass\n", "pkg/other.py": "X = 1\n"}
        with TempRepo(files) as repo:
            warm = Index(_ctx(repo.root))
            warm.info("pkg/other.py")
            warm.save()  # the index folder exists: later saves merge instead of starting it
            a, b = Index(_ctx(repo.root)), Index(_ctx(repo.root))
            a.info(first)
            b.info(second)
            a.save()
            b.save()  # the same shard file: b must not write back the shard as it was when b read it
            after = Index(_ctx(repo.root))
            self.assertEqual(set(after._shard(shard_of(first))), {first, second})
            (repo.root / first).unlink()
            repo.commit("gone")
            Index(_ctx(repo.root)).all()  # a full scan drops the entry of a file that is gone
            self.assertEqual(set(Index(_ctx(repo.root))._shard(shard_of(first))), {second})


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
            self.assertFalse(os.path.exists(used))  # the harness removes its cache when the process ends


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
