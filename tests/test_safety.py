"""What topomark must never read or run: secrets behind symbolic links or over the size limit,
paths outside the repository, and test paths pasted unquoted into shell commands."""

from __future__ import annotations

import os
import shlex
import tempfile
import unittest
from pathlib import Path

from tests.harness import TempRepo

SRC = {"src/app.py": "def run():\n    return 1\n", "tests/test_app.py": "from src.app import run\n\n\ndef test_run():\n"
       "    assert run() == 1\n"}


def _symlink(target: str, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError) as e:  # Windows without the privilege
        raise unittest.SkipTest(f"no symbolic links here: {e}") from e


class SymlinkSecretTests(unittest.TestCase):
    def test_link_to_a_secret_or_out_of_the_repo_is_never_indexed_or_read(self) -> None:
        with tempfile.TemporaryDirectory() as outside, TempRepo({**SRC, ".env": "SECRET_TOKEN=1\n"}, commit=False) as r:
            Path(outside, "priv.py").write_text("def leaked_fn():\n    pass\n", encoding="utf-8", newline="\n")
            _symlink(".env", r.root / "link.py")
            _symlink(str(Path(outside, "priv.py")), r.root / "linked.py")
            r.commit("links")
            self.assertEqual(r.json("search", "SECRET_TOKEN")["total"], 0)
            self.assertEqual(r.json("find", "leaked_fn", expect=4)["error"]["code"], "NOT_FOUND")
            self.assertEqual(r.json("outline", "linked.py", expect=4)["error"]["code"], "NOT_FOUND")
            self.assertEqual(r.json("outline", "link.py", expect=2)["error"]["code"], "REFUSED")
            self.assertEqual(r.json("symbol", "link.py#SECRET_TOKEN", expect=2)["error"]["code"], "REFUSED")
            listed = [f["path"] for f in r.json("outline", ".")["files"]]
            self.assertIn("src/app.py", listed)
            self.assertNotIn("link.py", listed)
            self.assertNotIn("linked.py", listed)

    def test_tracked_folder_replaced_by_a_link_is_not_read(self) -> None:
        import shutil

        with tempfile.TemporaryDirectory() as outside, TempRepo({**SRC, "lib/util.py": "def util():\n    pass\n"}) as r:
            Path(outside, "util.py").write_text("def leaked_fn():\n    pass\n", encoding="utf-8", newline="\n")
            shutil.rmtree(r.root / "lib")
            _symlink(outside, r.root / "lib")  # git still lists lib/util.py from the index
            self.assertEqual(r.json("search", "leaked_fn")["total"], 0)
            self.assertEqual(r.json("outline", "lib/util.py", expect=4)["error"]["code"], "NOT_FOUND")
            self.assertNotIn("lib/util.py", [f["path"] for f in r.json("outline", ".")["files"]])

    def test_link_inside_the_repo_still_works(self) -> None:
        with TempRepo(SRC, commit=False) as r:
            # native separators: Windows can't resolve a relative link target written with `/`
            _symlink(os.path.join("src", "app.py"), r.root / "alias.py")
            r.commit("alias")
            self.assertEqual(r.json("outline", "alias.py")["symbols"][0]["name"], "run")

    def test_large_secret_file_is_refused_before_reading(self) -> None:
        from topomark.index import MAX_BYTES

        with TempRepo(SRC) as r:
            (r.root / ".env.big").write_bytes(b"K=" + b"x" * (MAX_BYTES + 16) + b"\n")
            self.assertEqual(r.json("outline", ".env.big", expect=2)["error"]["code"], "REFUSED")


class LineEndingTests(unittest.TestCase):
    def test_crlf_files_read_like_lf_files(self) -> None:
        body = '"""Orders."""\n\n\nclass Order:\n    def total(self, tax):\n        return tax\n\n\nMAX_ITEMS = 5\n'
        with TempRepo({"src/lf.py": body}) as lf, TempRepo() as crlf:
            (crlf.root / "src").mkdir()
            with open(crlf.root / "src" / "lf.py", "w", encoding="utf-8", newline="") as fh:
                fh.write(body.replace("\n", "\r\n"))
            crlf.git("-c", "core.autocrlf=false", "add", "-A")
            crlf.commit("crlf")
            self.assertIn(b"\r\n", (crlf.root / "src" / "lf.py").read_bytes())
            for argv in (["outline", "src/lf.py"], ["symbol", "src/lf.py#Order.total"], ["find", "Order"],
                         ["search", "order total tax"], ["locate", "return tax"]):
                with self.subTest(argv=argv):
                    a, b = lf.json(*argv), crlf.json(*argv)
                    self.assertEqual(a, b)
                    self.assertNotIn("\r", crlf.cli(*argv)[1])


class SecretNameTests(unittest.TestCase):
    def test_what_counts_as_a_secret(self) -> None:
        from topomark.repo import is_secret

        secret = [".env", ".env.local", "app/.env.production", "deploy/id_rsa", "deploy/ID_RSA.pub", "certs/server.pem",
                  "certs/SERVER.KEY", "keys/prod.txt", "src/Keys/prod.json", "credentials.json", "aws/credentials",
                  "client_secret_123.json", "k8s/secrets.yaml", "helm/prod.secrets.yml", ".git-credentials",
                  "gcp/service-account-prod.json", "infra/prod.tfvars", "infra/prod.tfvars.json", "kubeconfig",
                  "kubeconfig.yaml", ".npmrc", "keys/id_ed25519.py", "src/keys/server.pem"]
        plain = ["src/auth/credentials.py", "src/keys/bindings.ts", "app/Keys/Shortcut.cs", "src/secrets_manager.py",
                 "docs/secrets.md", "src/environment.py", "config/settings.yaml", "infra/main.tf", "src/keyboard/keys.go"]
        for path in secret:
            with self.subTest(secret=path):
                self.assertTrue(is_secret(path))
        for path in plain:
            with self.subTest(plain=path):
                self.assertFalse(is_secret(path))

    def test_source_named_like_a_secret_is_read_and_the_data_next_to_it_is_not(self) -> None:
        files = {"src/auth/credentials.py": "def login_token():\n    return 1\n",
                 "src/auth/credentials.json": '{"password": "hunter2-do-not-leak"}\n',
                 "k8s/secrets.yaml": "password: hunter2-do-not-leak\n"}
        with TempRepo(files) as r:
            self.assertEqual(r.json("outline", "src/auth/credentials.py")["symbols"][0]["name"], "login_token")
            for path in ("src/auth/credentials.json", "k8s/secrets.yaml"):
                err = r.json("outline", path, expect=2)["error"]
                self.assertEqual(err["code"], "REFUSED")
            rc, out, _ = r.cli("search", "hunter2 password leak")
            self.assertIn("0 matches", out)
            self.assertEqual(r.json("locate", "hunter2-do-not-leak")["results"], [])


class OutsidePathTests(unittest.TestCase):
    def test_paths_outside_the_repo_are_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            os.makedirs(Path(parent, "outside"))
            priv = Path(parent, "outside", "priv.py")
            priv.write_text("def leaked_fn():\n    pass\n", encoding="utf-8", newline="\n")
            with TempRepo(SRC) as r:
                rel = os.path.relpath(priv, r.root).replace(os.sep, "/")
                self.assertTrue(rel.startswith("../"))
                for argv in (["outline", rel], ["outline", str(priv)], ["symbol", f"{rel}#leaked_fn"],
                             ["tests-for", rel], ["syntax", rel], ["impact", rel]):
                    with self.subTest(argv=argv):
                        err = r.json(*argv, expect=4)["error"]
                        self.assertEqual(err["code"], "NOT_FOUND")
                        self.assertNotIn("leaked_fn", err["message"])

    def test_docs_dir_outside_the_repo_is_refused_and_nothing_is_written(self) -> None:
        from topomark.errors import TopomarkError
        from topomark.repo import write_text

        with tempfile.TemporaryDirectory() as parent:
            with TempRepo(SRC) as r:
                up = os.path.relpath(Path(parent, "outside"), r.root).replace(os.sep, "/")
                for argv in (["init", "--dry-run", "--docs-dir", up], ["init", "--docs-dir", up]):
                    with self.subTest(argv=argv):
                        self.assertEqual(r.json(*argv, expect=2)["error"]["code"], "USAGE")
                r.write({"topomark.toml": f'[topomark]\ndocs_dir = "{up}"\n'})
                self.assertEqual(r.json("check", expect=3)["error"]["code"], "CONFIG")
                with self.assertRaises(TopomarkError):
                    write_text(r.root, f"{up}/README.md", "x\n")
            self.assertEqual(os.listdir(parent), [])

    def test_write_replaces_the_file_whole_and_leaves_nothing_behind(self) -> None:
        from topomark.repo import write_text

        with TempRepo(SRC) as r:
            target = r.root / "docs" / "map.md"
            write_text(r.root, "docs/map.md", "one\n")
            if os.name != "nt":
                os.chmod(target, 0o600)
            write_text(r.root, "docs/map.md", "two\n")
            self.assertEqual(r.read("docs/map.md"), "two\n")
            self.assertEqual(os.listdir(target.parent), ["map.md"])  # no temporary file left
            if os.name != "nt":
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_dot_slash_prefix_keeps_a_leading_dot(self) -> None:
        from topomark.commands._common import rel

        with TempRepo({**SRC, ".github/ci.yml": "on: push\n"}) as r:
            class Ctx:
                root = r.root

            elsewhere = tempfile.mkdtemp()
            cwd = os.getcwd()
            os.chdir(elsewhere)  # repo-relative, as with -C
            try:
                self.assertEqual(rel(Ctx, "./.github/ci.yml"), ".github/ci.yml")
                self.assertEqual(rel(Ctx, "././src/app.py"), "src/app.py")
                self.assertEqual(rel(Ctx, "src/x/../app.py"), "src/app.py")
                self.assertEqual(rel(Ctx, "src/"), "src/")
            finally:
                os.chdir(cwd)
                os.rmdir(elsewhere)
            self.assertEqual(r.json("outline", "./.github/ci.yml")["path"], ".github/ci.yml")


class RunnerQuotingTests(unittest.TestCase):
    def test_hostile_test_paths_are_quoted_safe_ones_unchanged(self) -> None:
        toml = '[[tests.runner]]\nmatch = "tests/"\ncommand = "python -m pytest {files}"\n'
        files = {"src/app.py": "def run():\n    return 1\n", "topomark.toml": toml,
                 "tests/test_app.py": "from src.app import run\n\n\ndef test_run():\n    assert run() == 1\n",
                 "tests/odd dir/test_$(touch pwned).py": "from src.app import run\n\n\ndef test_odd():\n"
                                                         "    assert run()\n"}
        with TempRepo(files) as r:
            cmd = r.json("tests-for", "src/app.py")["commands"][0]["commands"][0]
            self.assertEqual(shlex.split(cmd), ["python", "-m", "pytest", "tests/odd dir/test_$(touch pwned).py",
                                                "tests/test_app.py"])
            self.assertIn(" tests/test_app.py", cmd)  # a plain path is not quoted

    def test_template_quotes_and_empty_placeholders(self) -> None:
        from topomark.runners import fill_template as fill

        self.assertEqual(fill('t -f "{names}"', {"names": ["A.b", "x$y"]}, "|"), 't -f "A.b|x\\$y"')
        self.assertEqual(fill("t '{file}'", {"file": "it's.py"}), "t 'it'\\''s.py'")
        self.assertEqual(fill("pytest {file}::{class}::{method}", {"file": "a b.py", "class": "", "method": "m"}),
                         "pytest 'a b.py'::m")


if __name__ == "__main__":
    unittest.main()
