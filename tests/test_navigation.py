"""Navigation commands end to end on a small Python + JS + C# repo: outline, symbol,
find, refs (Type.Member, masking, decoys), impact (file and symbol), tests-for
(runners, method → class fallback, --diff with untracked files) and map (token
budget, focus personalisation)."""

from __future__ import annotations

import unittest

from tests.harness import TempRepo

CODE = {
    "src/core/router.py": '''
        """Routes requests to handlers."""

        class Router:
            """Maps paths to handlers."""

            def add(self, path, handler):
                self.routes[path] = handler

            def _private_helper(self):
                return 1

        def make_router():
            return Router()
        ''',
    "src/core/store.py": '''
        """Stores records."""

        from .router import Router

        class RecordStore:
            def save(self, record):
                # Router in a comment does not count
                text = "Router in a string does not count"
                return Router()
        ''',
    "src/core/helper.py": '''
        class Helper:
            pass
        ''',
    "web/widget.js": '''
        // A widget.
        export class Widget {
          render() { return 1; }
        }
        export function mountWidget(el) { return new Widget(el); }
        ''',
    "web/main.js": '''
        import { Widget, mountWidget } from "./widget.js";
        const w = mountWidget(document.body);
        console.log(Widget);
        ''',
    "web/widget.test.js": '''
        import { Widget } from "./widget.js";
        test("renders", () => { expect(new Widget().render()).toBe(1); });
        ''',
    "cs/PadBudget.cs": '''
        namespace Game
        {
            /// <summary>Time budget for one foot.</summary>
            public static class PadBudget
            {
                /// <summary>Lowest reaction window.</summary>
                public const float ReactionFloor = 0.75f;
                public const float Other = 1f;
            }
        }
        ''',
    "cs/Difficulty.cs": '''
        namespace Game
        {
            public class Difficulty
            {
                // ReactionFloor in a comment
                public bool Valid(float w) { return w >= PadBudget.ReactionFloor; }
                public string Label() { return "ReactionFloor"; }
            }
        }
        ''',
    "cs/Decoy.cs": '''
        namespace Game
        {
            public class Decoy
            {
                public float ReactionFloor = 2f;
                public float Twice() { return ReactionFloor * 2; }
            }
        }
        ''',
    "cs/Helper.cs": '''
        namespace Game
        {
            public class Helper { }
        }
        ''',
    "UnityTests/PadBudgetTests.cs": '''
        using NUnit.Framework;
        namespace Game.Tests
        {
            public class PadBudgetTests
            {
                [Test]
                public void Floor_is_positive() { Assert.Greater(PadBudget.ReactionFloor, 0f); }

                [Test]
                public void Other_is_one() { Assert.AreEqual(1f, PadBudget.Other); }

                [Test]
                public void Unrelated() { Assert.IsTrue(true); }
            }
        }
        ''',
    "tests/test_router.py": '''
        import unittest
        from core.router import Router

        class TestRouter(unittest.TestCase):
            def test_add(self):
                Router().add("/", None)

            def test_nothing(self):
                self.assertTrue(True)
        ''',
    "docs/guide.md": '''
        # Guide
        `PadBudget.ReactionFloor` is the law. See `src/core/router.py` and Router.
        ''',
}

TOML = '''
[[tests.runner]]
match = "UnityTests/"
command = "unity -runTests -testFilter \\"{names}\\""
names = "method"
join = "|"
max_names = {max_names}
fallback = "class"

[[tests.runner]]
match = "tests/"
command = "python -m pytest {files}"
names = "file"
'''


def make_repo(max_names: int = 1) -> TempRepo:
    return TempRepo({**CODE, "topomark.toml": TOML.replace("{max_names}", str(max_names))})


class NavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = make_repo()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    # ---------------------------------------------------------------- outline
    def test_outline_python_nested_and_private(self) -> None:
        d = self.repo.json("outline", "src/core/router.py")
        self.assertEqual(d["lang"], "python")
        quals = {s["qualname"]: s for s in d["symbols"]}
        self.assertIn("Router.add", quals)
        self.assertIn("Router._private_helper", quals)
        self.assertEqual(quals["Router.add"]["depth"], 1)
        self.assertEqual(quals["Router"]["doc"], "Maps paths to handlers.")
        d2 = self.repo.json("outline", "src/core/router.py", "--exported-only")
        self.assertNotIn("Router._private_helper", {s["qualname"] for s in d2["symbols"]})
        d3 = self.repo.json("outline", "src/core/router.py", "--depth", "1")
        self.assertEqual({s["qualname"] for s in d3["symbols"]}, {"Router", "make_router"})
        rc, out, _ = self.repo.cli("outline", "src/core/router.py")
        self.assertEqual(rc, 0)
        self.assertIn("class  class Router", out)
        self.assertIn("method -", out)  # private marker

    def test_outline_csharp_kinds_and_namespace(self) -> None:
        d = self.repo.json("outline", "cs/PadBudget.cs", "--kinds", "const")
        self.assertEqual(d["namespaces"], ["Game"])
        self.assertEqual([s["name"] for s in d["symbols"]], ["ReactionFloor", "Other"])
        self.assertEqual(d["symbols"][0]["doc"], "Lowest reaction window.")

    def test_outline_missing_file(self) -> None:
        d = self.repo.json("outline", "nope/missing.py", expect=4)
        self.assertEqual(d["error"]["code"], "NOT_FOUND")

    # ---------------------------------------------------------------- symbol
    def test_symbol_in_file(self) -> None:
        d = self.repo.json("symbol", "src/core/router.py#Router.add")
        (m,) = d["matches"]
        self.assertEqual(m["qualname"], "Router.add")
        self.assertIn("self.routes[path] = handler", m["source"])
        rc, out, _ = self.repo.cli("symbol", "src/core/router.py#add", "--context", "1")
        self.assertEqual(rc, 0)
        self.assertIn("5\t\n6\t    def add(self, path, handler):\n7\t", out)
        d = self.repo.json("symbol", "cs/PadBudget.cs#PadBudget.ReactionFloor", "--signature")
        self.assertEqual(d["matches"][0]["signature"], "public const float ReactionFloor = 0.75f")
        self.assertNotIn("source", d["matches"][0])

    def test_symbol_bare_name_and_errors(self) -> None:
        d = self.repo.json("symbol", "Widget")
        self.assertEqual(d["matches"][0]["path"], "web/widget.js")
        d = self.repo.json("symbol", "Helper", expect=4)
        self.assertTrue(d["ambiguous"])
        self.assertEqual({c["path"] for c in d["candidates"]}, {"src/core/helper.py", "cs/Helper.cs"})
        d = self.repo.json("symbol", "src/core/router.py#Nope", expect=4)
        self.assertEqual(d["error"]["code"], "NOT_FOUND")
        self.repo.json("symbol", "TotallyMissingName", expect=4)

    # ---------------------------------------------------------------- find
    def test_find(self) -> None:
        d = self.repo.json("find", "router")
        names = [r["qualname"] for r in d["results"]]
        self.assertEqual(names[0], "Router")  # case-insensitive exact name sorts first
        self.assertIn("make_router", names)
        d = self.repo.json("find", "Router.add", "--exact")
        self.assertEqual([r["qualname"] for r in d["results"]], ["Router.add"])
        d = self.repo.json("find", "e", "--kind", "const")
        self.assertTrue(d["results"])
        self.assertTrue(all(r["kind"] == "const" for r in d["results"]))
        self.repo.json("find", "zzzzqqq", expect=4)

    # ---------------------------------------------------------------- refs
    def test_refs_masks_comments_strings_and_declaration(self) -> None:
        d = self.repo.json("refs", "Router")
        sites = {(r["path"], r["line"]) for r in d["results"]}
        store = [r for r in d["results"] if r["path"] == "src/core/store.py"]
        self.assertEqual(len(store), 2)  # the import and the call, not the comment or the string
        self.assertNotIn(("src/core/router.py", 3), sites)  # the declaration itself
        self.assertIn(("src/core/router.py", 13), sites)  # make_router's `return Router()`
        self.assertTrue(any(r["test"] for r in d["results"]))
        self.assertEqual(d["test_files"], 1)
        d2 = self.repo.json("refs", "Router", "--no-tests")
        self.assertFalse(any(r["test"] for r in d2["results"]))
        d3 = self.repo.json("refs", "Router", "--area", "web")
        self.assertEqual(d3["sites"], 0)
        self.repo.json("refs", "Router", "--area", "no-such-area", expect=4)

    def test_refs_type_member_excludes_decoy(self) -> None:
        d = self.repo.json("refs", "PadBudget.ReactionFloor")
        paths = {r["path"] for r in d["results"]}
        self.assertIn("cs/Difficulty.cs", paths)
        self.assertIn("UnityTests/PadBudgetTests.cs", paths)
        self.assertNotIn("cs/Decoy.cs", paths)
        self.assertNotIn("cs/PadBudget.cs", paths)  # only the declaration lives there
        diff = [r for r in d["results"] if r["path"] == "cs/Difficulty.cs"]
        self.assertEqual(len(diff), 1)  # comment and string masked
        groups = {(g["test"], g["group"]) for g in d["groups"]}
        self.assertIn((False, "cs/"), groups)  # no code map: grouped by top-level directory
        d2 = self.repo.json("refs", "ReactionFloor")
        self.assertIn("cs/Decoy.cs", {r["path"] for r in d2["results"]})

    # ---------------------------------------------------------------- impact
    def test_impact_file(self) -> None:
        d = self.repo.json("impact", "src/core/router.py")
        self.assertEqual(d["kind"], "file")
        self.assertIn("Router", d["declares"])
        self.assertIn("src/core/store.py", d["fanin"]["prod_files"])
        self.assertEqual(d["fanin"]["test_files"], ["tests/test_router.py"])
        self.assertIn("docs/guide.md", d["mentions"]["files"])
        self.assertIsNone(d["area"])
        self.repo.json("impact", "src/none/missing.py", expect=4)

    def test_impact_symbol(self) -> None:
        d = self.repo.json("impact", "PadBudget.ReactionFloor")
        self.assertEqual(d["kind"], "symbol")
        self.assertEqual(d["definitions"][0]["path"], "cs/PadBudget.cs")
        self.assertEqual(d["tests"], ["UnityTests/PadBudgetTests.cs"])
        self.assertIn("cs/Difficulty.cs", d["callers"])
        self.assertEqual(d["mentions"]["files"], ["docs/guide.md"])
        self.repo.json("impact", "NoSuchThingAnywhere", expect=4)

    # ---------------------------------------------------------------- tests-for
    def test_tests_for_paths_method_fallback_to_class(self) -> None:
        d = self.repo.json("tests-for", "cs/PadBudget.cs")
        (t,) = d["tests"]
        self.assertEqual(t["path"], "UnityTests/PadBudgetTests.cs")
        self.assertEqual(t["methods"], ["PadBudgetTests.Floor_is_positive", "PadBudgetTests.Other_is_one"])
        (c,) = d["commands"]
        self.assertEqual(c["names"], "class")  # 2 methods > max_names 1
        self.assertEqual(c["commands"], ['unity -runTests -testFilter "PadBudgetTests"'])
        self.assertEqual(d["uncovered"], [])

    def test_tests_for_python_and_js(self) -> None:
        d = self.repo.json("tests-for", "src/core/router.py", "web/widget.js")
        tests = {t["path"]: t for t in d["tests"]}
        self.assertEqual(tests["tests/test_router.py"]["methods"], ["TestRouter.test_add"])
        self.assertTrue(tests["web/widget.test.js"]["whole_file"])  # it()/test() calls are not symbols
        cmds = {c["runner"]: c["commands"] for c in d["commands"]}
        self.assertEqual(cmds["tests/"], ["python -m pytest tests/test_router.py"])
        self.assertEqual(d["unmatched"], ["web/widget.test.js"])
        self.repo.json("tests-for", "no/such/file.py", expect=4)


class NavDiffTests(unittest.TestCase):
    def test_tests_for_diff_with_untracked_and_method_names(self) -> None:
        with make_repo(max_names=5) as repo:
            d = repo.json("tests-for")
            self.assertEqual(d["changed"], [])
            repo.write({"cs/PadBudget.cs": CODE["cs/PadBudget.cs"].replace("0.75f", "0.80f"),
                        "src/core/extra_thing.py": "class ExtraThing:\n    pass\n"})
            d = repo.json("tests-for", "--diff")
            self.assertEqual(d["source"], "diff")
            self.assertEqual(sorted(d["changed"]), ["cs/PadBudget.cs", "src/core/extra_thing.py"])
            self.assertEqual(d["uncovered"], ["src/core/extra_thing.py"])
            (c,) = d["commands"]
            self.assertEqual(c["names"], "method")
            self.assertEqual(c["commands"], ['unity -runTests -testFilter '
                                             '"PadBudgetTests.Floor_is_positive|PadBudgetTests.Other_is_one"'])
            repo.git("add", "cs/PadBudget.cs")
            d = repo.json("tests-for", "--staged")
            self.assertEqual(d["changed"], ["cs/PadBudget.cs"])
            repo.commit("more")
            d = repo.json("tests-for", "--since", "HEAD~1")
            self.assertIn("cs/PadBudget.cs", d["changed"])

    def test_changed_test_file_selected_whole(self) -> None:
        with make_repo() as repo:
            repo.write({"tests/test_router.py": CODE["tests/test_router.py"] + "\n"})
            d = repo.json("tests-for")
            (t,) = d["tests"]
            self.assertEqual(t["reason"], "changed test file")
            self.assertEqual(t["classes"], ["TestRouter"])


MAP_CODE = {
    "a/alpha_hub.py": "class AlphaHub:\n    def alpha_run(self):\n        return 1\n",
    "a/alpha_leaf.py": "from .alpha_hub import AlphaHub\n\nclass AlphaLeaf:\n    def go(self):\n        return AlphaHub()\n",
    "a/alpha_twig.py": "from .alpha_hub import AlphaHub\n\nclass AlphaTwig:\n    def go(self):\n        return AlphaHub()\n",
    "b/beta_hub.py": "class BetaHub:\n    def beta_run(self):\n        return 1\n",
    "b/beta_leaf.py": "from .beta_hub import BetaHub\n\nclass BetaLeaf:\n    def go(self):\n        return BetaHub()\n",
}


class MapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = TempRepo(MAP_CODE)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def order(self, *argv: str) -> list[str]:
        return [f["path"] for f in self.repo.json("map", "--tokens", "4000", *argv)["files"]]

    def test_focus_changes_ranking(self) -> None:
        plain = self.order()
        self.assertLess(plain.index("a/alpha_hub.py"), plain.index("b/beta_hub.py"))
        focused = self.order("--focus", "b/beta_leaf.py")
        self.assertLess(focused.index("b/beta_hub.py"), focused.index("a/alpha_hub.py"))
        by_name = self.order("--focus", "BetaLeaf")
        self.assertLess(by_name.index("b/beta_hub.py"), by_name.index("a/alpha_hub.py"))

    def test_token_budget_respected(self) -> None:
        from topomark.contract import estimate_tokens

        small = self.repo.json("map", "--tokens", "12")
        self.assertLessEqual(small["estimated_tokens"], 12)
        big = self.repo.json("map", "--tokens", "4000")
        self.assertGreater(sum(len(f["symbols"]) for f in big["files"]),
                           sum(len(f["symbols"]) for f in small["files"]))
        rc, out, _ = self.repo.cli("map", "--tokens", "40")
        self.assertEqual(rc, 0)
        self.assertLessEqual(estimate_tokens(out.rstrip("\n") + "\n"), 40)
        self.assertIn("│", out)
        self.assertIn(":\n", out)

    def test_area_filter_by_directory(self) -> None:
        paths = self.order("--area", "b")
        self.assertTrue(paths and all(p.startswith("b/") for p in paths))
        self.repo.json("map", "--area", "zzz", expect=4)


if __name__ == "__main__":
    unittest.main()
