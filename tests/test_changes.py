"""``changes``: diff hunks mapped to symbols on both sides, interface (added, removed, signature,
header) vs body, who still references a changed interface, tests and runner commands, code-map
rows to review; working tree, --staged and --since; untracked and deleted files."""

from __future__ import annotations

import unittest

from tests.harness import TempRepo

BASE = {
    "topomark.toml": '[[tests.runner]]\nmatch = "tests/"\ncommand = "python3 -m unittest {names}"\nnames = "class"\n',
    "src/shop/cart.py": '''
        """Shopping cart."""


        class Cart:
            def add_item(self, item):
                self.items = [item]
                return item

            def total_price(self):
                return 0


        def legacy_checkout(cart):
            return cart
        ''',
    "src/shop/pay.py": '''
        from .cart import Cart, legacy_checkout


        def pay():
            return legacy_checkout(Cart())
        ''',
    "src/shop/gone.py": "def obsolete_helper():\n    return 1\n",
    "tests/test_cart.py": '''
        import unittest
        from shop.cart import Cart

        class CartTest(unittest.TestCase):
            def test_total(self):
                Cart().total_price()
        ''',
    "docs/codemap/README.md": "[shop](shop.md)\n",
    "docs/codemap/shop.md": "---\narea: shop\ntitle: Shop\nsummary: s\nscope:\n  - src/\n---\n\n## Files\n\n"
                            "| file | summary | impact |\n|---|---|---|\n| `src/shop/cart.py` | cart | fan-in 1/1 |\n"
                            "| `src/shop/pay.py` | pay | fan-in 0/0 |\n| `src/shop/gone.py` | gone | fan-in 0/0 |\n",
}

CHANGED_CART = '''"""Shopping cart, with discounts."""


class Cart:
    def add_item(self, item):
        self.items = [item, item]
        return item

    def total_price(self, currency):
        return 0

    def discount(self):
        return 1
'''


def changes_of(d: dict) -> dict[str, dict[str, str]]:
    return {f["path"]: {s["qualname"]: s["change"] for s in f["symbols"]} for f in d["files"]}


class ChangesTest(unittest.TestCase):
    def test_working_tree_interface_body_reach_tests_rows(self) -> None:
        with TempRepo(BASE) as r:
            r.cli("stamp", "--baseline")
            r.commit("baseline")
            r.write({"src/shop/cart.py": CHANGED_CART, "src/shop/extra.py": "def brand_new():\n    return 2\n"})
            (r.root / "src/shop/gone.py").unlink()
            d = r.json("changes")
            got = changes_of(d)
            self.assertEqual(got["src/shop/cart.py"], {"Cart.add_item": "body", "Cart.total_price": "signature",
                                                       "Cart.discount": "added", "legacy_checkout": "removed"})
            self.assertEqual(got["src/shop/extra.py"], {"brand_new": "added"})
            self.assertEqual(got["src/shop/gone.py"], {"obsolete_helper": "removed"})
            cart = next(f for f in d["files"] if f["path"] == "src/shop/cart.py")
            self.assertTrue(cart["header_changed"])
            sig = next(s for s in cart["symbols"] if s["qualname"] == "Cart.total_price")
            self.assertEqual((sig["old_signature"], sig["signature"]),
                             ("def total_price(self)", "def total_price(self, currency)"))
            reach = {x["qualname"]: x for x in d["interface"]}
            self.assertEqual(reach["legacy_checkout"]["callers"], ["src/shop/pay.py"])
            self.assertEqual(reach["Cart.total_price"]["tests"], ["tests/test_cart.py"])
            self.assertEqual(reach["obsolete_helper"]["sites"], 0)
            self.assertNotIn("brand_new", reach)  # nothing can call what was just added
            self.assertEqual([t["path"] for t in d["tests"]], ["tests/test_cart.py"])
            self.assertEqual(d["commands"][0]["commands"], ["python3 -m unittest CartTest"])
            rows = {x["path"]: x for x in d["review"]}
            self.assertEqual(rows["src/shop/cart.py"]["stamp"], "changed")
            self.assertEqual(rows["src/shop/cart.py"]["area_file"], "docs/codemap/shop.md")
            self.assertEqual(rows["src/shop/gone.py"]["status"], "deleted")
            self.assertEqual(d["counts"], {"files": 3, "interface": 6, "body": 1})
            rc, out, _ = r.cli("changes")
            self.assertIn("legacy_checkout (removed): 2 sites in 1 prod + 0 test files: src/shop/pay.py  "
                          "still referenced after removal", out)
            self.assertIn("  signature function  Cart.total_price", out.replace("method   ", "function "))

    def test_staged_and_since(self) -> None:
        with TempRepo(BASE) as r:
            first = r.git("rev-parse", "HEAD").strip()
            r.write({"src/shop/pay.py": "from .cart import Cart\n\n\ndef pay():\n    return Cart()\n\n\ndef refund():\n    return 0\n"})
            r.git("add", "src/shop/pay.py")
            r.write({"src/shop/cart.py": CHANGED_CART})  # not staged
            staged = changes_of(r.json("changes", "--staged"))
            self.assertEqual(staged, {"src/shop/pay.py": {"pay": "body", "refund": "added"}})
            r.commit("pay")
            since = changes_of(r.json("changes", "--since", first))
            self.assertEqual(since["src/shop/pay.py"], {"pay": "body", "refund": "added"})
            self.assertIn("Cart.discount", since["src/shop/cart.py"])
            self.assertEqual(r.json("changes", "--since", "nope", expect=4)["error"]["code"], "NOT_FOUND")
            self.assertEqual(r.cli("changes", "--staged", "--since", first)[0], 2)

    def test_blank_lines_belong_to_no_one(self) -> None:
        with TempRepo(BASE) as r:
            text = r.read("src/shop/cart.py").replace("        return 0\n", "        return 0\n\n    def coupon(self):\n"
                                                                            "        return 5\n")
            r.write({"src/shop/cart.py": text + "\n\ndef tail_helper():\n    return 1\n"})
            f = r.json("changes")["files"][0]
            self.assertEqual({s["qualname"]: s["change"] for s in f["symbols"]},
                             {"Cart.coupon": "added", "tail_helper": "added"})
            self.assertFalse(f["outside_declarations"])

    def test_outside_declarations_and_nothing(self) -> None:
        with TempRepo(BASE) as r:
            self.assertEqual(r.json("changes")["files"], [])
            self.assertIn("no code changed", r.cli("changes")[1])
            text = r.read("src/shop/pay.py").replace("from .cart import Cart, legacy_checkout",
                                                     "from .cart import Cart, legacy_checkout  # noqa")
            r.write({"src/shop/pay.py": text})
            d = r.json("changes")
            self.assertEqual(d["files"][0]["symbols"], [])
            self.assertTrue(d["files"][0]["outside_declarations"])



class DiffParsingTest(unittest.TestCase):
    """Files git names only in the ``diff --git`` header, paths with spaces, hunk lines that look
    like headers."""

    def test_spaces_mode_binary_and_header_lookalikes(self) -> None:
        files = {"src/my dir/a b.py": "def f(a):\n    return a\n", "src/tool.py": "def run():\n    return 1\n",
                 "src/blob.py": "def blob():\n    return 1\n",
                 "src/doc.py": 'def doc():\n    """\n-- a dashed line\n    """\n    return 1\n'}
        with TempRepo(files) as r:
            r.write({"src/my dir/a b.py": "def f(a, b):\n    return a\n",
                     "src/doc.py": 'def doc():\n    """\n++ a plus line\n    """\n    return 1\n'})
            with open(r.root / "src/blob.py", "ab") as fh:
                fh.write(b"\0")  # git now calls it binary: no ---/+++ lines
            d = r.json("changes")
            self.assertEqual(changes_of(d), {"src/my dir/a b.py": {"f": "signature"}, "src/doc.py": {"doc": "body"},
                                             "src/blob.py": {}})
            self.assertEqual({f["path"]: f["status"] for f in d["files"]},
                             {"src/my dir/a b.py": "modified", "src/doc.py": "modified", "src/blob.py": "modified"})
            r.git("update-index", "--chmod=+x", "src/tool.py")  # a mode change alone (works without core.fileMode)
            d = r.json("changes", "--staged")
            self.assertEqual([(f["path"], f["status"], f["symbols"]) for f in d["files"]],
                             [("src/tool.py", "modified", [])])

    def test_header_only_files(self) -> None:
        from topomark.changes import parse_diff

        text = ('diff --git a/new.py b/new.py\nnew file mode 100644\nindex 0000000..e69de29\n'
                'diff --git a/gone.py b/gone.py\ndeleted file mode 100644\nindex e69de29..0000000\n'
                'diff --git "a/q\\"x.py" "b/q\\"x.py"\nold mode 100644\nnew mode 100755\n'
                'diff --git a/s p.py b/s p.py\nindex 1..2 100644\n--- a/s p.py\t\n+++ b/s p.py\t\n@@ -1 +1,2 @@\n-x\n+y\n+z\n')
        got = {p: (f.status, sorted(f.old), sorted(f.new)) for p, f in parse_diff(text).items()}
        self.assertEqual(got, {"new.py": ("added", [], []), "gone.py": ("deleted", [], []),
                               'q"x.py': ("modified", [], []), "s p.py": ("modified", [1], [1, 2])})


if __name__ == "__main__":
    unittest.main()
