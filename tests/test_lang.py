"""Language adapters against small synthetic fixtures (tests/fixtures/lang/<lang>/).

``GOLDEN`` pins every symbol each fixture yields as ``(qualname, kind, start,
end, exported)`` in order; the focused tests below pin signatures, docs, the
review surface and the fan-in ``types`` where an adapter has a rule worth
guarding. Regenerate a golden only after reading the new outline.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

import tests.harness  # noqa: F401  (puts src/ on sys.path)
from topomark.lang.registry import analyze

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "lang"


def info_of(rel: str):
    with open(FIXTURES / rel, encoding="utf-8") as fh:
        return analyze(rel, fh.read())


def sym(info, qualname: str, kind: str | None = None):
    for s in info.symbols:
        if s.qualname == qualname and (kind is None or s.kind == kind):
            return s
    raise AssertionError(f"no symbol {qualname!r} in {[s.qualname for s in info.symbols]}")


GOLDEN = {
    "c/util.c": [
        ("MAX_LEN", "macro", 5, 5, False),
        ("SQUARE", "macro", 6, 6, False),
        ("counter", "var", 8, 8, False),
        ("greeting", "var", 9, 9, True),
        ("Point", "struct", 11, 13, True),
        ("Point.x", "field", 12, 12, True),
        ("Node", "struct", 15, 18, True),
        ("Node.next", "field", 16, 16, True),
        ("Node.value", "field", 17, 17, True),
        ("Color", "enum", 20, 20, True),
        ("add", "function", 22, 32, True),
        ("helper", "function", 34, 37, False),
        ("platform_init", "function", 40, 40, True),
        ("make_node", "function", 46, 49, True),
    ],
    "cpp/shape.hpp": [
        ("geo", "namespace", 5, 39, False),
        ("detail", "namespace", 6, 6, False),
        ("helper", "function", 6, 6, True),
        ("Shape", "class", 8, 19, True),
        ("Shape.Shape", "constructor", 10, 10, True),
        ("Shape.~Shape", "destructor", 11, 11, True),
        ("Shape.area", "method", 12, 12, True),
        ("Shape.kSides", "const", 13, 13, True),
        ("Shape.name_", "field", 15, 15, True),
        ("Shape.id_", "field", 17, 17, False),
        ("Shape.secret", "method", 18, 18, False),
        ("Box", "struct", 21, 29, True),
        ("Box.value", "field", 23, 23, True),
        ("Box.Box", "constructor", 24, 24, True),
        ("Box.area", "method", 25, 25, True),
        ("Box.operator==", "operator", 26, 26, True),
        ("Box.extra_", "field", 28, 28, False),
        ("Mode", "enum", 31, 31, True),
        ("Id", "type", 33, 33, True),
        ("c_api", "function", 36, 36, True),
        ("geo.Shape.area", "method", 41, 41, True),
        ("geo.Shape.~Shape", "destructor", 43, 43, True),
        ("raw", "var", 45, 45, True),
        ("main", "function", 47, 49, True),
    ],
    "csharp/Player.cs": [
        ("Player", "class", 7, 54, True),
        ("Player.ReactionFloor", "const", 11, 11, True),
        ("Player.Path", "field", 12, 12, False),
        ("Player.Name", "property", 13, 13, True),
        ("Player.Id", "property", 14, 14, True),
        ("Player.Changed", "event", 15, 15, True),
        ("Player._id", "field", 16, 16, False),
        ("Player.Volume", "property", 18, 23, True),
        ("Player._volume", "field", 24, 24, False),
        ("Player.Player", "constructor", 26, 26, True),
        ("Player.ToString", "method", 28, 28, True),
        ("Player.operator +", "operator", 30, 30, True),
        ("Player.this[]", "indexer", 32, 32, True),
        ("Player.EditorOnly", "method", 35, 39, True),
        ("Player.LoadAsync", "method", 41, 45, False),
        ("Player.Mode", "enum", 47, 47, True),
        ("Player.Score", "record", 49, 49, True),
        ("Player.Nested", "class", 51, 51, False),
        ("Player.Nested.Inner", "method", 51, 51, True),
        ("Player.~Player", "destructor", 53, 53, False),
        ("IGame", "interface", 56, 56, True),
        ("IGame.Begin", "method", 56, 56, True),
        ("IGame.Title", "property", 56, 56, True),
        ("Tick", "delegate", 58, 58, True),
        ("Vec", "record", 60, 60, True),
    ],
    "dart/widget.dart": [
        ("kMaxTaps", "const", 4, 5, True),
        ("_private", "var", 7, 7, False),
        ("CounterPage", "class", 9, 19, True),
        ("CounterPage.CounterPage", "constructor", 11, 11, True),
        ("CounterPage.title", "field", 13, 13, True),
        ("CounterPage.named", "constructor", 15, 15, True),
        ("CounterPage.createState", "method", 17, 18, True),
        ("_CounterPageState", "class", 21, 47, False),
        ("_CounterPageState._count", "field", 22, 22, False),
        ("_CounterPageState.greeting", "const", 23, 24, True),
        ("_CounterPageState._increment", "method", 26, 30, False),
        ("_CounterPageState.label", "getter", 32, 32, True),
        ("_CounterPageState.count", "setter", 34, 36, True),
        ("_CounterPageState.build", "method", 38, 45, True),
        ("Loud", "mixin", 49, 51, True),
        ("Loud.shout", "method", 50, 50, True),
        ("StringX", "extension", 53, 55, True),
        ("StringX.twice", "method", 54, 54, True),
        ("Color", "enum", 57, 57, True),
        ("Planet", "enum", 59, 65, True),
        ("Planet.Planet", "constructor", 63, 63, True),
        ("Planet.mass", "field", 64, 64, True),
        ("Callback", "type", 67, 67, True),
        ("main", "function", 69, 71, True),
    ],
    "data/Game.asmdef": [
        ("name", "key", 2, 2, True),
        ("references", "key", 3, 3, True),
        ("autoReferenced", "key", 4, 6, True),
    ],
    "data/config.yaml": [
        ("server", "key", 2, 6, True),
        ("database", "key", 7, 8, True),
        ("quoted key", "key", 9, 10, True),
    ],
    "data/pyproject.toml": [
        ("project", "table", 1, 3, True),
        ("tool.ruff", "table", 4, 6, True),
        ("tool.mypy.overrides", "table", 7, 9, True),
    ],
    "data/settings.jsonc": [
        ("editor.tabSize", "key", 3, 3, True),
        ("files.exclude", "key", 4, 4, True),
        ("url", "key", 5, 7, True),
    ],
    "go/server.go": [
        ("MaxConns", "const", 10, 10, True),
        ("minConns", "const", 11, 11, False),
        ("A", "const", 12, 12, True),
        ("B", "const", 12, 12, True),
        ("defaultName", "var", 15, 15, False),
        ("Option", "type", 17, 17, True),
        ("Server", "struct", 19, 25, True),
        ("Server.Name", "field", 21, 21, True),
        ("Server.port", "field", 22, 22, False),
        ("Server.Client", "field", 23, 23, True),
        ("Server.Mutex", "field", 24, 24, True),
        ("Handler", "interface", 27, 30, True),
        ("Handler.Serve", "method", 28, 28, True),
        ("Handler.close", "method", 29, 29, False),
        ("New", "function", 32, 39, True),
        ("Server.Start", "method", 41, 43, True),
        ("Server.stop", "method", 45, 45, False),
        ("Map", "function", 47, 49, True),
        ("table", "var", 51, 53, False),
    ],
    "js/component.jsx": [
        ("App", "function", 4, 11, True),
        ("helper", "function", 13, 13, True),
        ("Store", "class", 15, 18, False),
        ("Store.state", "field", 16, 16, True),
        ("Store.create", "method", 17, 17, True),
        ("module.exports", "exports", 20, 20, True),
    ],
    "kotlin/Shapes.kt": [
        ("MAX", "const", 6, 6, True),
        ("Shape", "interface", 8, 11, True),
        ("Shape.area", "method", 10, 10, True),
        ("Circle", "class", 13, 23, True),
        ("Circle.area", "method", 14, 14, True),
        ("Circle.secret", "method", 16, 18, False),
        ("Circle.Companion", "object", 20, 22, True),
        ("Circle.Companion.unit", "method", 21, 21, True),
        ("Square", "class", 25, 32, True),
        ("Square.area", "method", 29, 29, True),
        ("Square.label", "property", 30, 30, False),
        ("Kind", "enum", 34, 38, True),
        ("Kind.twice", "method", 37, 37, True),
        ("Registry", "object", 40, 43, True),
        ("Registry.register", "method", 41, 42, True),
        ("describe", "function", 45, 47, True),
        ("Shapes", "type", 49, 49, True),
        ("hidden", "function", 51, 51, False),
    ],
    "markdown/guide.md": [
        ("Guide", "h1", 1, 15, True),
        ("Install", "h2", 5, 13, True),
        ("Details", "h3", 12, 13, True),
        ("Usage", "h2", 14, 15, True),
    ],
    "markdown/setext.md": [
        ("Title", "h1", 6, 15, True),
        ("Sub", "h2", 9, 15, True),
    ],
    "objc/View.m": [
        ("ViewController", "class", 4, 9, True),
        ("ViewController.title", "property", 7, 7, True),
        ("ViewController.reload", "method", 8, 8, True),
        ("ViewController", "class", 11, 26, True),
        ("ViewController.viewDidLoad", "method", 13, 16, True),
        ("ViewController.add:to:", "method", 18, 20, True),
        ("ViewController.shared", "method", 22, 24, True),
    ],
    "python/models.py": [
        ("MAX_USERS", "const", 7, 7, True),
        ("LONG", "const", 9, 9, False),
        ("User", "class", 12, 31, True),
        ("User.Meta", "class", 15, 16, True),
        ("User.__init__", "method", 18, 19, True),
        ("User.title", "method", 21, 23, True),
        ("User.save", "method", 25, 31, True),
        ("make_user", "function", 34, 35, True),
        ("_private", "function", 38, 43, False),
        ("fetch_all", "function", 46, 47, False),
    ],
    "rust/lib.rs": [
        ("MAX", "const", 4, 5, True),
        ("COUNTER", "const", 6, 6, False),
        ("Point", "struct", 8, 12, True),
        ("Unit", "struct", 14, 14, True),
        ("Shape", "enum", 16, 21, True),
        ("Area", "trait", 23, 28, True),
        ("Area.area", "method", 24, 24, True),
        ("Area.name", "method", 25, 27, True),
        ("Point", "impl", 30, 38, False),
        ("Point.new", "method", 31, 35, True),
        ("Point.private_helper", "method", 37, 37, False),
        ("Point", "impl", 40, 44, True),
        ("Point.fmt", "method", 41, 43, True),
        ("inner", "module", 46, 48, True),
        ("inner.helper", "function", 47, 47, True),
        ("tests", "module", 50, 50, False),
        ("square", "macro", 52, 54, False),
        ("crate_fn", "function", 56, 58, True),
        ("abs", "function", 61, 61, False),
    ],
    "shell/deploy.sh": [
        ("log", "function", 5, 5, True),
        ("build", "function", 7, 12, True),
        ("upload", "function", 14, 18, True),
    ],
    "sql/schema.sql": [
        ("users", "table", 2, 5, True),
        ("idx_users_name", "index", 8, 8, True),
        ("active_users", "view", 10, 11, True),
    ],
    "swift/Model.swift": [
        ("User", "struct", 4, 25, True),
        ("User.id", "property", 6, 6, True),
        ("User.name", "property", 7, 7, True),
        ("User.cache", "property", 8, 8, False),
        ("User.init", "constructor", 10, 13, True),
        ("User.greeting", "property", 15, 17, True),
        ("User.rename", "method", 19, 24, True),
        ("Direction", "enum", 27, 37, True),
        ("Direction.flipped", "method", 31, 36, True),
        ("Store", "protocol", 39, 43, True),
        ("Store.Item", "type", 40, 40, True),
        ("Store.load", "method", 41, 41, True),
        ("Store.count", "property", 42, 42, True),
        ("User", "extension", 45, 47, True),
        ("User.==", "method", 46, 46, True),
        ("Platform", "class", 50, 50, True),
        ("helper", "function", 59, 59, False),
    ],
    "ts/service.ts": [
        ("MAX_RETRIES", "const", 6, 6, True),
        ("Id", "type", 9, 9, True),
        ("Repo", "interface", 11, 14, True),
        ("Repo.find", "method", 12, 12, True),
        ("Repo.name", "field", 13, 13, True),
        ("Level", "enum", 16, 16, True),
        ("UserService", "class", 18, 39, True),
        ("UserService.name", "field", 20, 20, True),
        ("UserService.#secret", "field", 21, 21, False),
        ("UserService.cache", "field", 22, 22, False),
        ("UserService.count", "field", 23, 23, True),
        ("UserService.constructor", "constructor", 25, 25, True),
        ("UserService.find", "method", 27, 30, True),
        ("UserService.size", "getter", 32, 32, True),
        ("UserService.handler", "method", 34, 36, True),
        ("UserService.helper", "method", 38, 38, False),
        ("overload", "function", 41, 41, True),
        ("overload", "function", 42, 42, True),
        ("overload", "function", 43, 45, True),
        ("arrow", "function", 47, 49, True),
        ("main", "function", 51, 53, True),
        ("foo", "namespace", 55, 57, True),
        ("bar", "function", 56, 56, True),
        ("Utils", "namespace", 59, 61, True),
        ("clamp", "function", 60, 60, True),
    ],
}


class GoldenOutlines(unittest.TestCase):
    def test_every_fixture_has_a_golden(self) -> None:
        on_disk = {p.relative_to(FIXTURES).as_posix() for p in FIXTURES.rglob("*")
                   if p.is_file() and not p.name.startswith(".")}
        self.assertEqual(on_disk, set(GOLDEN))

    def test_outlines_match(self) -> None:
        for rel, expected in GOLDEN.items():
            with self.subTest(rel):
                got = [(s.qualname, s.kind, s.start, s.end, s.exported) for s in info_of(rel).symbols]
                self.assertEqual(got, expected)


class Signatures(unittest.TestCase):
    def test_dart(self) -> None:
        i = info_of("dart/widget.dart")
        self.assertEqual(i.lang, "dart")
        self.assertEqual(sym(i, "CounterPage.CounterPage").signature,
                         "const CounterPage({super.key, this.title = 'x'})")
        self.assertEqual(sym(i, "_CounterPageState.label").signature, "String get label")
        self.assertEqual(sym(i, "kMaxTaps").doc, "Max taps before reset.")
        self.assertIn("enum Color = red,green,blue", i.surface)
        self.assertIn("enum Planet = mercury,venus", i.surface)
        self.assertNotIn("_increment", i.surface)
        self.assertEqual(i.types, ["CounterPage", "_CounterPageState", "Loud", "StringX", "Color", "Planet",
                                   "Callback"])

    def test_kotlin(self) -> None:
        i = info_of("kotlin/Shapes.kt")
        self.assertEqual(sym(i, "describe").signature, "fun Shape.describe(): String")
        self.assertEqual(sym(i, "Circle.area").signature, "override fun area(): Double")
        self.assertEqual(sym(i, "Registry.register").attrs, ["JvmStatic"])
        self.assertEqual(sym(i, "Shape").doc, "A shape.")
        self.assertIn("enum Kind = A,B", i.surface)

    def test_swift(self) -> None:
        i = info_of("swift/Model.swift")
        self.assertTrue(sym(i, "User.name").exported, "private(set) only restricts the setter")
        self.assertEqual(sym(i, "User.==").signature, "public static func == (a: User, b: User) -> Bool")
        self.assertIn("enum Direction = north,south,east", i.surface)
        self.assertEqual(i.types, ["User", "Direction", "Store", "Platform"])
        self.assertEqual(sym(i, "Platform").doc, "", "#if lines are not doc comments")

    def test_go(self) -> None:
        i = info_of("go/server.go")
        self.assertEqual(sym(i, "Server.Start").signature, "func (s *Server) Start() error")
        self.assertEqual(sym(i, "New").doc, "New creates a server.")
        self.assertEqual(sym(i, "Server", "struct").doc, "Server holds state.")
        self.assertIn("Map", i.types)
        self.assertNotIn("minConns", i.surface)

    def test_rust(self) -> None:
        i = info_of("rust/lib.rs")
        self.assertEqual(sym(i, "Point", "struct").signature, "pub struct Point<'a>")
        self.assertEqual(sym(i, "Point", "struct").attrs, ["derive(Debug, Clone)"])
        self.assertTrue(sym(i, "Point.fmt").exported, "trait impl methods are public through the trait")
        self.assertIn("enum Shape = Circle,Square,Empty", i.surface)
        self.assertEqual(i.types, ["MAX", "Point", "Unit", "Shape", "Area", "inner", "tests", "crate_fn"])
        self.assertEqual(sym(i, "Point.fmt").container, "Point")
        self.assertIn("trait fmt::Display", [a for s in i.symbols if s.kind == "impl" for a in s.attrs])

    def test_c(self) -> None:
        i = info_of("c/util.c")
        self.assertEqual(i.lang, "c")
        self.assertEqual(i.header, ["/* Utility functions. */"])
        self.assertEqual(sym(i, "add").doc, "Adds two ints.")
        self.assertIn("#else void posix_only(int flags);", i.surface)
        self.assertIn("Point", i.types)

    def test_cpp(self) -> None:
        i = info_of("cpp/shape.hpp")
        self.assertEqual(i.lang, "cpp")
        self.assertEqual(sym(i, "Shape.Shape").signature, "Shape() = default")
        self.assertEqual(sym(i, "geo.Shape.area").doc, "", "a trailing comment on the previous line is not doc")
        self.assertEqual(sym(i, "Box.Box").signature, "explicit Box(T v) : value{v}, extra_(0)")

    def test_objc(self) -> None:
        i = info_of("objc/View.m")
        self.assertEqual(i.lang, "objc")
        self.assertEqual(sym(i, "ViewController.add:to:").signature, "- (NSInteger)add:(NSInteger)a to:(NSInteger)b")

    def test_csharp(self) -> None:
        i = info_of("csharp/Player.cs")
        self.assertEqual(sym(i, "Player").doc, "A player.")
        self.assertEqual(sym(i, "Player").attrs, ["Serializable"])
        self.assertEqual(sym(i, "Player.Volume").attrs, ["SerializeField, Range(0, 1)"])
        self.assertIn("public const float ReactionFloor = 0.75f", i.surface)
        self.assertIn("#else public void RuntimeOnly()", i.surface)
        self.assertIn("enum Mode = Easy,Normal,Hard", i.surface)
        self.assertEqual(i.types, ["Player", "IGame", "Vec"])

    def test_typescript(self) -> None:
        i = info_of("ts/service.ts")
        self.assertEqual(i.lang, "ts")
        self.assertEqual(sym(i, "UserService").signature,
                         "@Injectable({ scope: 'app' }) export class UserService<T extends { id: Id }> implements Repo<T>")
        self.assertEqual(sym(i, "arrow").signature, "export const arrow = async (x: number): Promise<number> =>")
        self.assertEqual(sym(i, "foo").kind, "namespace")
        self.assertEqual(i.types.count("overload"), 1)

    def test_jsx_and_commonjs(self) -> None:
        i = info_of("js/component.jsx")
        self.assertTrue(sym(i, "helper").exported, "named in module.exports")
        self.assertIn("module.exports = { App, helper }", i.surface)

    def test_python(self) -> None:
        i = info_of("python/models.py")
        self.assertEqual(sym(i, "User.save").signature, "async def save( self, force: bool = False, ) -> bool")
        self.assertEqual(sym(i, "User.title").attrs, ["property"])
        self.assertEqual(sym(i, "User").doc, "A user record.")
        self.assertIn("__all__ = MAX_USERS, User, make_user", i.surface)
        self.assertNotIn("inner", [s.name for s in i.symbols], "nested functions are bodies")
        self.assertNotIn("fake", [s.name for s in i.symbols], "def inside a string is not a def")

    def test_shell_sql_data_markdown(self) -> None:
        self.assertEqual(sym(info_of("shell/deploy.sh"), "build").end, 12, "heredoc braces are not code")
        sql = info_of("sql/schema.sql")
        self.assertIn("name TEXT NOT NULL DEFAULT 'a;b' )", sql.surface)
        yaml = info_of("data/config.yaml")
        self.assertIn(".server.hosts[].url", yaml.surface.split("\n"))
        self.assertNotIn(".server.hosts.name.url", yaml.surface)
        jsonc = info_of("data/settings.jsonc")
        self.assertIn(".files.exclude.**/.git", jsonc.surface.split("\n"))
        asmdef = info_of("data/Game.asmdef")
        self.assertIn('"Arcade.UI"', asmdef.surface, "asmdef surface keeps values")
        toml = info_of("data/pyproject.toml")
        self.assertIn(".tool.mypy.overrides[].module", toml.surface.split("\n"))
        md = info_of("markdown/setext.md")
        self.assertEqual([s.name for s in md.symbols], ["Title", "Sub"], "front matter and list rules skipped")


class Edges(unittest.TestCase):
    """Inline snippets for rules that don't need a whole fixture."""

    def outline(self, path: str, text: str) -> list[tuple[str, str]]:
        return [(s.qualname, s.kind) for s in analyze(path, text).symbols]

    def test_js_export_default_object_lists_handlers(self) -> None:
        text = "export default {\n  async fetch(req, env) { return 1 },\n  scheduled: async (e) => {},\n  name,\n}\n"
        i = analyze("w.js", text)
        self.assertEqual(sym(i, "default").signature, "export default { fetch(), scheduled(), name }")
        self.assertIn("export default { fetch(), scheduled(), name }", i.surface)

    def test_js_regex_literal_does_not_open_a_comment(self) -> None:
        text = 'const CSS = fs\n  .read()\n  .replace(/\\/\\*[\\s\\S]*?\\*\\//g, "");\n\nexport function after() {}\n'
        self.assertIn(("after", "function"), self.outline("a.ts", text))

    def test_csharp_inactive_branch_public_api_in_surface(self) -> None:
        text = ("class R {\n#if UNITY_EDITOR\n    public static float RenderScale = 1f;\n#else\n"
                "    public static float RenderScale = 1.25f;\n    private int hidden;\n#endif\n}\n")
        i = analyze("R.cs", text)
        self.assertIn("#else public static float RenderScale = 1.25f;", i.surface)
        self.assertNotIn("hidden", i.surface)
        self.assertEqual([s.name for s in i.symbols], ["R", "RenderScale"])

    def test_csharp_doc_keeps_cref_and_inline_code(self) -> None:
        text = ('class A {\n    /// <summary>Uses <see cref="PadInputRouter"/> and `Foo.Bar`, see '
                '<paramref name="x"/>.</summary>\n    public void M(int x) {}\n}\n')
        self.assertEqual(sym(analyze("a.cs", text), "A.M").doc, "Uses PadInputRouter and Foo.Bar, see x.")

    def test_js_doc_for_newline_terminated_languages(self) -> None:
        text = "// banner\n\n// Builds the thing.\nexport function build() {}\n"
        self.assertEqual(sym(analyze("b.js", text), "build").doc, "Builds the thing.")

    def test_go_const_group_items_on_their_own_lines(self) -> None:
        text = "package p\n\nconst (\n\tA = iota\n\tb\n)\n"
        i = analyze("p.go", text)
        self.assertEqual([(s.name, s.line, s.exported) for s in i.symbols], [("A", 4, True), ("b", 5, False)])

    def test_kotlin_annotation_line_attaches(self) -> None:
        text = "@Composable\nfun Greeting(name: String) {\n    Text(\"Hi $name\")\n}\n"
        s = sym(analyze("G.kt", text), "Greeting")
        self.assertEqual((s.start, s.end, s.attrs), (1, 4, ["Composable"]))

    def test_c_typedef_function_pointer_and_prototype(self) -> None:
        text = "typedef void (*Handler)(int);\nint run(Handler h, int n);\nstatic int hidden(void);\n"
        self.assertEqual([(s.name, s.kind, s.exported) for s in analyze("h.h", text).symbols],
                         [("Handler", "type", True), ("run", "function", True), ("hidden", "function", False)])

    def test_c_macros_in_headers_are_exported(self) -> None:
        text = "#ifndef UTIL_H\n#define UTIL_H\n#define VERSION 3\n#endif\n"
        i = analyze("util.h", text)
        self.assertEqual([(s.name, s.kind, s.exported) for s in i.symbols], [("VERSION", "macro", True)])
        self.assertIn("#define VERSION 3", i.surface)

    def test_swift_where_clause_on_next_line(self) -> None:
        text = "func sorted<T>(_ xs: [T]) -> [T]\n    where T: Comparable {\n    xs\n}\n"
        s = sym(analyze("s.swift", text), "sorted")
        self.assertEqual((s.start, s.end), (1, 4))

    def test_line_end_optional_and_force_unwrap_do_not_continue(self) -> None:
        self.assertEqual(self.outline("a.swift", "class A {\n    weak var d: D?\n    var x = 1\n}\n"),
                         [("A", "class"), ("A.d", "property"), ("A.x", "property")])
        self.assertEqual(self.outline("a.kt", "import a.b.*\n\nclass Foo {}\n"), [("Foo", "class")])
        self.assertIn(("f", "function"), self.outline("a.ts", "const el = x!\nexport function f() {}\n"))

    def test_c_capitalized_types_are_not_macros(self) -> None:
        text = "struct S { FILE *fp; BOOL flag = TRUE; EXPORT_API int api(void); };\nHANDLE make(void);\n"
        self.assertEqual(self.outline("s.h", text),
                         [("S", "struct"), ("S.fp", "field"), ("S.flag", "field"), ("S.api", "method"),
                          ("make", "function")])

    def test_dart_generated_l10n_is_fast(self) -> None:
        body = "".join(f"  /// Doc {k}.\n  String get key{k};\n\n" for k in range(2000))
        text = "abstract class AppLocalizations {\n" + body + "}\n"
        t0 = time.perf_counter()
        i = analyze("lib/l10n/app_localizations.dart", text)
        self.assertEqual(len(i.symbols), 2001)
        self.assertLess(time.perf_counter() - t0, 1.5)  # ~0.2 s on a laptop; generous for CI


class Imports(unittest.TestCase):
    """``FileInfo.imports``: specifiers as written, never part of the review surface."""

    def test_python(self) -> None:
        text = (
            '"""Doc that says: from fake import nothing."""\n'
            "from __future__ import annotations\n\n"
            "import os, sys as system\n"
            "import a.b.c as abc\n"
            "from . import Result, other as o\n"
            "from .. import docs as D\n"
            "from .lang.base import (\n    FileInfo,  # why\n    Symbol,\n)\n"
            "from pkg.mod import *\n"
            's = "import notreal"\n\n'
            "def run(name):\n"
            "    from ..navigate import Nav\n"
            '    importlib.import_module("plugins.static")\n'
            '    return importlib.import_module(f"plugins.{name}")\n\n'
            "def import_module(x):\n    pass\n")
        info = analyze("src/pkg/cmd/x.py", text)
        self.assertEqual(info.imports, ["os", "sys", "a.b.c", ".", ".Result", ".other", "..", "..docs",
                                        ".lang.base", ".lang.base.FileInfo", ".lang.base.Symbol", "pkg.mod",
                                        "..navigate", "..navigate.Nav", "plugins.static", "<dynamic>"])

    def test_js_ts(self) -> None:
        text = (
            '// header: import x from "nope"\n'
            'import React from "react";\n'
            "import { a,\n  b } from './x.js';\n"
            'import type { T } from "../types";\n'
            'import "./side-effect.css";\n'
            'export * from "./top";\n'
            "export { c } from './c'\n"
            'const fs = require("fs");\n'
            'const lazy = () => import("./lazy");\n'
            "const page = (n) => import(`./pages/${n}`);\n"
            "const s = \"import { z } from 'zzz'\";\n"
            'const arr = Array.from("abc");\n'
            "console.log(import.meta.url);\n")
        info = analyze("web/app.ts", text)
        self.assertEqual(info.imports, ["react", "./x.js", "../types", "./side-effect.css", "./top", "./c", "fs",
                                        "./lazy", "<dynamic>"])

    def test_imports_do_not_change_the_surface(self) -> None:
        cases = [("m.py", "def f():\n    return 1\n", "import os\nfrom .y import z\n\ndef f():\n    return 1\n"),
                 ("m.ts", "export function f() { return 1; }\n",
                  'import { a } from "./a";\nexport function f() { return 1; }\nconst l = () => import("./l");\n')]
        for path, plain, with_imports in cases:
            with self.subTest(path=path):
                a, b = analyze(path, plain), analyze(path, with_imports)
                self.assertEqual(a.surface, b.surface)
                self.assertEqual(a.imports, [])
                self.assertTrue(b.imports)


if __name__ == "__main__":
    unittest.main()
