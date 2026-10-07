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

    def test_non_ascii_paths_and_unknown_revisions(self) -> None:
        name = "src/\u65e5\u672c.py"  # git quotes it without -z
        with TempRepo({name: "def kanji():\n    return 1\n", "tests/test_kanji.py":
                       "from src import kanji\n\n\ndef test_kanji():\n    assert kanji\n"}) as repo:
            repo.write({name: "def kanji():\n    return 2\n"})
            d = repo.json("tests-for")
            self.assertEqual((d["changed"], d["deleted"]), ([name], []))
            self.assertEqual([t["path"] for t in d["tests"]], ["tests/test_kanji.py"])
            self.assertEqual(repo.json("syntax")["checked"], [name])
            self.assertEqual([(f["path"], f["status"]) for f in repo.json("changes")["files"]], [(name, "modified")])
            for argv in (["tests-for", "--since", "no-such-rev"], ["changes", "--since", "no-such-rev"]):
                with self.subTest(argv=argv):
                    self.assertEqual(repo.json(*argv, expect=4)["error"]["code"], "NOT_FOUND")


SUPPORT_FILES = {
    "src/pkg/__init__.py": "",
    "src/pkg/core.py": "class RouterThing:\n    def go(self):\n        return 1\n",
    "tests/harness.py": "from pkg.core import RouterThing\n\n\ndef make_router():\n    return RouterThing()\n",
    "tests/test_core.py": "import unittest\nfrom tests.harness import make_router\n\n\nclass CoreTests(unittest.TestCase):\n"
                          "    def test_go(self):\n        self.assertEqual(make_router().go(), 1)\n",
    "topomark.toml": '[[tests.runner]]\nmatch = "tests/"\ncommand = "python -m unittest {names}"\nnames = "file"\n',
}


class TestSupportTests(unittest.TestCase):
    """A shared harness under tests/ is support code: never picked to run, followed to its tests."""

    def test_harness_mentioning_the_name_leads_to_the_tests_using_it(self) -> None:
        with TempRepo(SUPPORT_FILES) as repo:
            d = repo.json("tests-for", "src/pkg/core.py")
            self.assertEqual([t["path"] for t in d["tests"]], ["tests/test_core.py"])
            self.assertEqual(d["commands"][0]["commands"], ["python -m unittest tests/test_core.py"])
            self.assertEqual(d["uncovered"], [])
            d = repo.json("tests-for", "tests/harness.py")  # a changed helper: the tests that use it
            self.assertEqual([(t["path"], t["methods"]) for t in d["tests"]],
                             [("tests/test_core.py", ["CoreTests.test_go"])])


class FindRankingTests(unittest.TestCase):
    def test_code_before_docs_and_data(self) -> None:
        files = {
            "config/routes.json": '{\n  "routes": {"home": "/"}\n}\n',
            "docs/routing.md": "# Routing table\n\nHow requests are routed.\n",
            "src/core/router.py": "class Router:\n    pass\n",
            "tests/test_router.py": "def test_routing():\n    pass\n",
        }
        with TempRepo(files) as repo:
            rows = [(r["path"], r["qualname"]) for r in repo.json("find", "rout")["results"]]
            self.assertEqual(rows[0], ("src/core/router.py", "Router"))
            self.assertEqual(rows[1], ("tests/test_router.py", "test_routing"))  # test code, then prose and data
            self.assertEqual({p for p, _ in rows[2:]}, {"config/routes.json", "docs/routing.md"})
            exact = [(r["path"], r["qualname"]) for r in repo.json("find", "routes")["results"]]
            self.assertEqual(exact[0], ("config/routes.json", "routes"))  # exactness still comes first
            mapped = [f["path"] for f in repo.json("map", "--tokens", "500")["files"]]
            self.assertEqual(mapped, ["src/core/router.py"])  # data files are not code either


RECALL_FILES = {
    "pkg/a.py": "def alpha_value(x):\n    return x * 2\n",
    "pkg/b.py": "from pkg.a import alpha_value\n\n\nclass BetaThing:\n    def run(self):\n        return alpha_value(1)\n",
    "tests/test_b.py": "import unittest\n\n\nclass TestBeta(unittest.TestCase):\n    def test_run(self):\n"
                       "        from pkg.b import BetaThing\n        self.assertEqual(BetaThing().run(), 2)\n\n"
                       "    def test_other(self):\n        self.assertTrue(True)\n",
    "chain/leaf.py": "def leaf_value(x):\n    return x\n",
    "chain/mid.py": "from chain.leaf import leaf_value\n\n\ndef mid_value(x):\n    return leaf_value(x) + 1\n",
    "chain/top.py": "from .mid import mid_value\n\n\ndef top_value(x):\n    return mid_value(x) * 2\n",
    "tests/test_top.py": "import unittest\nfrom chain.top import top_value\n\n\nclass TestTop(unittest.TestCase):\n"
                         "    def test_top(self):\n        self.assertEqual(top_value(1), 4)\n",
    "web/lib/leaf.ts": "export function leafThing(x: number) { return x; }\n",
    "web/lib/top.ts": 'import { leafThing } from "./leaf";\nexport function topThing(x: number) { return leafThing(x); }\n',
    "web/lib/index.ts": 'export * from "./top";\n',
    "web/lib.test.ts": 'import { topThing } from "./lib";\ntest("t", () => { expect(topThing(1)).toBe(1); });\n',
    "hub/core.py": "def core_hub_value():\n    return 1\n",
    "plugins/loader.py": "import importlib\n\n\ndef load(name):\n    return importlib.import_module(f'plugins.{name}')\n",
    **{f"users/u{k:02d}.py": f"from hub.core import core_hub_value\n\n\ndef user_{k:02d}():\n    return core_hub_value()\n"
       for k in range(31)},
    "topomark.toml": '[[tests.runner]]\nmatch = "tests/"\ncommand = "python3 -m unittest {names}"\nnames = "class"\n'
                     'suite = "python3 -m unittest discover -s tests"\n\n'
                     '[[tests.runner]]\nmatch = "web/"\ncommand = "npx vitest run {files}"\n',
}


class TestsForRecallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = TempRepo(RECALL_FILES)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_function_only_file_reaches_tests_through_its_caller(self) -> None:
        d = self.repo.json("tests-for", "pkg/a.py")
        (t,) = d["tests"]
        self.assertEqual(t["path"], "tests/test_b.py")
        self.assertEqual(t["via"], ["pkg/b.py"])
        self.assertEqual(t["classes"], ["TestBeta"])  # imports a caller: whole class, not one method
        self.assertEqual(d["commands"][0]["commands"], ["python3 -m unittest TestBeta"])
        self.assertEqual((d["depth"], d["uncovered"], d["suite_commands"]), (2, [], []))
        rc, out, _ = self.repo.cli("tests-for", "pkg/a.py")
        self.assertIn("tests/test_b.py  classes TestBeta  (imports pkg/b.py)", out)

    def test_depth_zero_is_the_name_match_alone(self) -> None:
        d = self.repo.json("tests-for", "pkg/a.py", "--depth", "0")
        self.assertEqual((d["tests"], d["uncovered"], d["depth"]), ([], ["pkg/a.py"], 0))
        self.assertEqual(d["suite_commands"], ["python3 -m unittest discover -s tests"])
        self.repo.json("tests-for", "pkg/a.py", "--depth", "-1", expect=2)

    def test_import_chain_is_followed_transitively(self) -> None:
        d = self.repo.json("tests-for", "chain/leaf.py")
        (t,) = d["tests"]
        self.assertEqual((t["path"], t["via"]), ("tests/test_top.py", ["chain/mid.py", "chain/top.py"]))
        self.assertEqual(t["reason"], "imports chain/top.py via chain/mid.py")
        d = self.repo.json("tests-for", "chain/leaf.py", "--depth", "1")
        self.assertEqual((d["tests"], d["uncovered"]), ([], ["chain/leaf.py"]))

    def test_barrel_files_cost_no_hop(self) -> None:
        d = self.repo.json("tests-for", "web/lib/leaf.ts", "--depth", "1")
        (t,) = d["tests"]
        self.assertEqual((t["path"], t["via"]), ("web/lib.test.ts", ["web/lib/top.ts", "web/lib/index.ts"]))
        self.assertEqual(d["commands"][0]["commands"], ["npx vitest run web/lib.test.ts"])

    def test_too_many_callers_falls_back_to_the_suite(self) -> None:
        d = self.repo.json("tests-for", "hub/core.py")
        self.assertEqual((d["tests"], d["uncovered"], d["limited"]), ([], ["hub/core.py"], ["hub/core.py"]))
        self.assertEqual(d["suite_commands"], ["python3 -m unittest discover -s tests"])
        self.assertEqual(d["dynamic_loaders"], ["plugins/loader.py"])
        rc, out, _ = self.repo.cli("tests-for", "hub/core.py")
        self.assertEqual(rc, 0)
        self.assertIn("hub/core.py  (over 30 callers: too central to pick by name)", out)
        self.assertIn("may miss tests: modules are also loaded by computed names in plugins/loader.py", out)
        self.assertIn("run the whole suite:\n  python3 -m unittest discover -s tests", out)

    def test_suite_must_be_a_string(self) -> None:
        with TempRepo({"a.py": "X = 1\n", "topomark.toml": '[[tests.runner]]\nmatch = "t/"\ncommand = "x"\nsuite = 3\n'}) as r:
            d = r.json("tests-for", "a.py", expect=3)
            self.assertIn("suite must be a string", d["error"]["message"])


IMPORT_FILES = {
    "src/pkg/__init__.py": "",
    "src/pkg/core.py": "class Core:\n    pass\n",
    "src/pkg/util.py": "from .core import Core\n\n\ndef helper():\n    return Core()\n",
    "src/pkg/sub/deep.py": "from .. import util\nfrom ..core import Core\n",
    "src/app.py": "import json\nimport pkg.util\nfrom pkg.core import Core as C\n",
    "tools/json.py": "X = 1\n",
    "web/lib/math.ts": "export function add(a: number, b: number) { return a + b; }\n",
    "web/lib/index.ts": 'export * from "./math";\n',
    "web/app.ts": 'import { add } from "./lib";\nimport { add as plus } from "./lib/math.js";\nimport React from "react";\n',
    "web/alias.ts": 'import { add } from "@/lib/math";\n',
    "web/lazy.ts": "export const load = (n: string) => import(`./pages/${n}`);\n",
    "tests/test_util.py": "from pkg.util import helper\n\n\ndef test_helper():\n    helper()\n",
}


class ImportEdgeTests(unittest.TestCase):
    def test_resolver(self) -> None:
        from topomark.lang.base import DYNAMIC
        from topomark.navigate import ImportResolver

        r = ImportResolver(IMPORT_FILES)
        cases = [("src/pkg/util.py", ".core", "src/pkg/core.py"),
                 ("src/pkg/sub/deep.py", "..", "src/pkg/__init__.py"),
                 ("src/pkg/sub/deep.py", "..util", "src/pkg/util.py"),
                 ("src/app.py", "pkg.util", "src/pkg/util.py"),  # src/ layout: module-path suffix
                 ("src/app.py", "pkg.core.Core", None),  # a class, not a submodule
                 ("src/app.py", "json", None),  # standard library, though tools/json.py exists
                 ("web/app.ts", "./lib", "web/lib/index.ts"),
                 ("web/app.ts", "./lib/math.js", "web/lib/math.ts"),  # .js written for a .ts file
                 ("web/alias.ts", "@/lib/math", "web/lib/math.ts"),
                 ("web/app.ts", "react", None),
                 ("web/lazy.ts", DYNAMIC, None)]
        for importer, spec, want in cases:
            with self.subTest(spec=spec):
                self.assertEqual(r.resolve(importer, spec), want)
        near = ImportResolver(["a/x/util.py", "b/util.py", "a/x/main.py"])
        self.assertEqual(near.resolve("a/x/main.py", "util"), "a/x/util.py")

    def test_repo_package_named_like_the_standard_library(self) -> None:
        from topomark.navigate import ImportResolver

        r = ImportResolver(["calendar/__init__.py", "calendar/slots.py", "app/main.py", "utils/__init__.py",
                            "utils/json.py", "src/email/x.py", "src/run.py", "pkg/__init__.py", "pkg/calendar/slots.py"])
        cases = [("app/main.py", "calendar.slots", "calendar/slots.py"), ("app/main.py", "calendar", "calendar/__init__.py"),
                 ("app/main.py", "json", None), ("app/main.py", "utils.json", "utils/json.py"),
                 ("src/run.py", "email.x", "src/email/x.py"), ("app/main.py", "email.x", None), ("app/main.py", "os", None)]
        for importer, spec, want in cases:
            with self.subTest(importer=importer, spec=spec):
                self.assertEqual(r.resolve(importer, spec), want)
        with TempRepo({"calendar/__init__.py": "", "calendar/slots.py": "def make_slots():\n    return []\n",
                       "app/main.py": "from calendar.slots import make_slots\n"}) as repo:
            self.assertEqual(repo.json("impact", "calendar/slots.py")["importers"]["files"], ["app/main.py"])

    def test_impact_lists_importers(self) -> None:
        with TempRepo(IMPORT_FILES) as repo:
            d = repo.json("impact", "src/pkg/core.py")
            self.assertEqual(d["importers"]["files"], ["src/app.py", "src/pkg/sub/deep.py", "src/pkg/util.py"])
            self.assertEqual(d["importers"]["count"], 3)
            d = repo.json("impact", "src/pkg/util.py")
            self.assertEqual(d["importers"]["files"], ["src/app.py", "src/pkg/sub/deep.py", "tests/test_util.py"])
            d = repo.json("impact", "web/lib/math.ts")
            self.assertEqual(d["importers"]["files"], ["web/alias.ts", "web/app.ts", "web/lib/index.ts"])
            rc, out, _ = repo.cli("impact", "web/lib/math.ts")
            self.assertIn("importers (3):\n  web/alias.ts", out)

    def test_enclosing_symbol(self) -> None:
        from topomark.lang.registry import analyze
        from topomark.navigate import enclosing_symbol

        info = analyze("m.py", "class A:\n    def m(self):\n        x = 1\n        return x\n\n\ndef f():\n    pass\n")
        got = {n: getattr(enclosing_symbol(info, n), "qualname", None) for n in (1, 3, 5, 8)}
        self.assertEqual(got, {1: "A", 3: "A.m", 5: None, 8: "f"})


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
