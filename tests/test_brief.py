"""``brief``: area row, outline, callers ranked by coupling, tests and the run command, for a
file or a name; ambiguous names list candidates; the token budget trims the outline first."""

from __future__ import annotations

import unittest

from tests.harness import TempRepo

FILES = {
    "topomark.toml": '[[tests.runner]]\nmatch = "tests/"\ncommand = "python3 -m unittest {names}"\nnames = "method"\n',
    "src/core/ledger.py": '''
        """Keeps the books."""

        class LedgerBook:
            """A book of entries."""

            def post_entry(self, entry):
                return entry

            def balance(self):
                return 0

        def open_ledger(name):
            return LedgerBook()

        def close_ledger(book):
            return book
        ''',
    "src/core/report.py": '''
        from .ledger import LedgerBook, open_ledger, close_ledger

        def monthly():
            book = open_ledger("m")
            close_ledger(book)
            return LedgerBook()
        ''',
    "src/web/view.py": '''
        from core.ledger import LedgerBook

        def show():
            return LedgerBook()
        ''',
    "src/web/dup_a.py": "def render_page():\n    pass\n",
    "src/web/dup_b.py": "def render_page():\n    pass\n",
    "tests/test_ledger.py": '''
        import unittest
        from core.ledger import LedgerBook

        class LedgerTest(unittest.TestCase):
            def test_post(self):
                LedgerBook().post_entry(1)

            def test_other(self):
                self.assertTrue(True)
        ''',
    "docs/codemap/README.md": "[core](core.md)\n",
    "docs/codemap/core.md": "---\narea: core\ntitle: Core\nsummary: core\nscope:\n  - src/\n---\n\n## Files\n\n"
                            "| file | summary | impact |\n|---|---|---|\n"
                            "| `src/core/ledger.py` | the books: LedgerBook | fan-in 2/1 |\n",
}


class BriefTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = TempRepo(FILES)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_file_brief(self) -> None:
        d = self.repo.json("brief", "src/core/ledger.py")
        self.assertEqual(d["area"]["file"], "docs/codemap/core.md")
        self.assertIn("the books: LedgerBook", d["area"]["row"])
        self.assertEqual([o["qualname"] for o in d["outline"]],
                         ["LedgerBook", "LedgerBook.post_entry", "LedgerBook.balance", "open_ledger", "close_ledger"])
        self.assertEqual([c["path"] for c in d["callers"]], ["src/core/report.py", "src/web/view.py"])
        self.assertEqual(d["callers"][0]["uses"], ["LedgerBook", "open_ledger", "close_ledger"])
        self.assertEqual([t["path"] for t in d["tests"]], ["tests/test_ledger.py"])
        self.assertEqual(d["tests"][0]["methods"], ["LedgerTest.test_post"])
        self.assertEqual(d["commands"][0]["commands"], ["python3 -m unittest LedgerTest.test_post"])
        self.assertEqual([(r["path"], r["role"]) for r in d["related"]],
                         [("src/core/report.py", "caller"), ("src/web/view.py", "caller"), ("tests/test_ledger.py", "test")])
        rc, out, _ = self.repo.cli("brief", "src/core/ledger.py")
        self.assertEqual(rc, 0)
        self.assertIn("run: python3 -m unittest LedgerTest.test_post", out)
        self.assertIn("src/core/report.py  (uses LedgerBook, open_ledger, close_ledger; imports it)", out)

    def test_symbol_brief(self) -> None:
        d = self.repo.json("brief", "LedgerBook")
        self.assertEqual((d["path"], d["symbol"]["qualname"]), ("src/core/ledger.py", "LedgerBook"))
        self.assertEqual([o["qualname"] for o in d["outline"]], ["LedgerBook.post_entry", "LedgerBook.balance"])
        self.assertEqual(d["callers"][0], {"path": "src/core/report.py", "sites": 2})
        self.assertEqual([t["path"] for t in d["tests"]], ["tests/test_ledger.py"])
        self.assertNotIn("src/core/ledger.py", [r["path"] for r in d["related"]])
        one = self.repo.json("brief", "src/core/ledger.py#LedgerBook.post_entry")
        self.assertEqual(one["symbol"]["qualname"], "LedgerBook.post_entry")
        self.assertEqual(one["tests"][0]["methods"], ["LedgerTest.test_post"])

    def test_ambiguous_and_missing(self) -> None:
        d = self.repo.json("brief", "render_page", expect=4)
        self.assertTrue(d["ambiguous"])
        self.assertEqual({c["path"] for c in d["candidates"]}, {"src/web/dup_a.py", "src/web/dup_b.py"})
        self.assertEqual(self.repo.json("brief", "src/nope.py", expect=4)["error"]["code"], "NOT_FOUND")
        self.assertEqual(self.repo.json("brief", "Nope", expect=4)["error"]["code"], "NOT_FOUND")

    def test_budget_trims_outline_first(self) -> None:
        full = self.repo.json("brief", "src/core/ledger.py")
        self.assertEqual(full["trimmed"], [])
        small = self.repo.json("brief", "src/core/ledger.py", "--tokens", "120")
        self.assertEqual(small["trimmed"][0], "outline")
        self.assertLess(len(small["outline"]), small["outline_total"])
        self.assertEqual(small["callers"], full["callers"])
        rc, out, _ = self.repo.cli("brief", "src/core/ledger.py", "--tokens", "120")
        self.assertIn("more (`topomark outline src/core/ledger.py`)", out)


if __name__ == "__main__":
    unittest.main()
