"""``search``: BM25 over symbol names (split at case and underscores, stemmed), docs and paths;
production above tests and code above docs; test names lend their score to the code they use;
code-map rows count for their file; output capped by --limit and --tokens, filtered by --area."""

from __future__ import annotations

import unittest

from tests.harness import TempRepo

FILES = {
    "src/store/cache.py": '''
        """On-disk cache of parsed files."""

        def cache_directory(root):
            """Where the per-repo cache lives."""
            return root

        class EntryWriter:
            def write_entries(self, rows):
                return rows
        ''',
    "src/store/guard.py": '''
        def read_guarded(path):
            return open(path).read()
        ''',
    "src/web/routes.ts": '''
        // HTTP route table.
        export function registerRouteHandlers(app: any): void {}
        export class RouteTable { lookupRoute(path: string) { return path; } }
        ''',
    "docs/cache.md": "# Cache directory\n\nThe cache directory is per repo.\n",
    "tests/test_guard.py": '''
        import unittest
        from store.guard import read_guarded

        class GuardTest(unittest.TestCase):
            def test_refuses_secret_paths(self):
                read_guarded(".env")

            def test_cache_directory_helper(self):
                pass
        ''',
}


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = TempRepo(FILES)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def results(self, *argv: str) -> list[str]:
        d = self.repo.json("search", *argv)
        return [f"{r['path']}#{r['qualname']}" if r["qualname"] else r["path"] for r in d["results"]]

    def test_names_split_and_stemmed(self) -> None:
        self.assertEqual(self.results("route handlers")[0], "src/web/routes.ts#registerRouteHandlers")
        self.assertEqual(self.results("lookup routes")[0], "src/web/routes.ts#RouteTable.lookupRoute")
        self.assertEqual(self.results("writing entry")[0], "src/store/cache.py#EntryWriter.write_entries")

    def test_code_before_docs_and_tests(self) -> None:
        got = self.results("cache directory")
        self.assertEqual(got[0], "src/store/cache.py#cache_directory")
        self.assertLess(got.index("src/store/cache.py#cache_directory"), got.index("docs/cache.md#Cache directory"))
        self.assertLess(got.index("src/store/cache.py#cache_directory"),
                        got.index("tests/test_guard.py#GuardTest.test_cache_directory_helper"))

    def test_test_name_leads_to_the_code_it_uses(self) -> None:
        d = self.repo.json("search", "refuses", "secret", "paths")
        top = d["results"][0]
        self.assertEqual((top["path"], top["qualname"]), ("src/store/guard.py", "read_guarded"))
        self.assertEqual(top["via"], ["tests/test_guard.py::GuardTest.test_refuses_secret_paths"])

    def test_caps_area_tokens_and_determinism(self) -> None:
        d = self.repo.json("search", "cache", "route", "--limit", "2")
        self.assertEqual(len(d["results"]), 2)
        self.assertTrue(d["truncated"])
        self.assertGreater(d["total"], 2)
        rc, out, _ = self.repo.cli("search", "cache", "route", "--limit", "2")
        self.assertEqual(rc, 0)
        self.assertIn(f"… {d['total'] - 2} more (raise --limit", out)
        self.assertEqual(self.repo.json("search", "cache", "route", "--limit", "2"), d)
        web = self.results("cache", "route", "--area", "src/web")
        self.assertTrue(web and all(r.startswith("src/web/") for r in web), web)
        small = self.repo.json("search", "cache", "route", "--tokens", "40")
        self.assertLess(small["shown"], self.repo.json("search", "cache", "route")["shown"])
        self.assertGreaterEqual(small["shown"], 1)

    def test_stop_words_only_is_a_usage_error(self) -> None:
        self.assertEqual(self.repo.json("search", "the", "of", expect=2)["error"]["code"], "USAGE")


class SearchPackingTest(unittest.TestCase):
    def test_whitespace_in_a_heading_or_name_does_not_break_the_index(self) -> None:
        with TempRepo({"notes.md": "# Notes\n\n## Alpha\tbeta\n\ntext\n", "a.py": "def alpha():\n    pass\n"}) as repo:
            d = repo.json("search", "alpha", "beta")
            self.assertIn(("notes.md", "Alpha beta"), [(h["path"], h["qualname"]) for h in d["results"]])


class SearchCodeMapTest(unittest.TestCase):
    def test_area_row_counts_for_its_file(self) -> None:
        files = {"svc/a.py": "def alpha():\n    pass\n", "svc/b.py": "def beta():\n    pass\n",
                 "docs/codemap/README.md": "[svc](svc.md)\n",
                 "docs/codemap/svc.md": "---\narea: svc\ntitle: Svc\nsummary: s\nscope:\n  - svc/\n---\n\n## Files\n\n"
                                        "| file | summary | impact |\n|---|---|---|\n"
                                        "| `svc/b.py` | settles invoices nightly | fan-in 0/0 |\n"}
        with TempRepo(files) as r:
            got = [res["path"] for res in r.json("search", "settles", "invoices")["results"]]
            self.assertEqual(got[0], "svc/b.py")


if __name__ == "__main__":
    unittest.main()
