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
                  "kubeconfig.yaml", ".npmrc", "keys/id_ed25519.py", "src/keys/server.pem",
                  ".envrc", "deploy/prod.env", "deploy/id_dsa", "putty/server.ppk", "apple/AuthKey_X.p8",
                  "vault.kdbx", ".pgpass", "web/.htpasswd", ".s3cfg", ".boto", ".vault-token", ".dockercfg",
                  ".docker/config.json", "home/.docker/config.json", ".kube/config", "vpn/office.ovpn",
                  "infra/terraform.tfstate", "infra/terraform.tfstate.backup"]
        plain = ["src/auth/credentials.py", "src/keys/bindings.ts", "app/Keys/Shortcut.cs", "src/secrets_manager.py",
                 "docs/secrets.md", "src/environment.py", "config/settings.yaml", "infra/main.tf", "src/keyboard/keys.go",
                 "src/env.py", "docker/config.json", "src/kube/config.go", "docs/environment.md",
                 "src/keys/bindings.hxx", "src/credentials.inl", "src/keys/map.c++"]
        # shell and SQL have adapters and still count: that is where tokens and dumped rows get written
        secret += ["src/keys/run.sh", "db/credentials.sql", "keys/rotate.zsh"]
        for path in secret:
            with self.subTest(secret=path):
                self.assertTrue(is_secret(path))
        for path in plain:
            with self.subTest(plain=path):
                self.assertFalse(is_secret(path))

    def test_the_documented_list_is_the_list(self) -> None:
        from topomark.repo import SECRET_NAME_PATTERNS, SECRET_PATTERNS

        root = Path(__file__).resolve().parents[1]
        for doc in ("SECURITY.md", "docs/config.md"):
            text = " ".join((root / doc).read_text(encoding="utf-8").split())
            for p in SECRET_PATTERNS + SECRET_NAME_PATTERNS:
                with self.subTest(doc=doc, pattern=p):
                    self.assertIn(f"`{p}`", text)

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


class SymlinkWriteTests(unittest.TestCase):
    """A file a command owns may be a symbolic link planted by the repository: never write through
    one that leads out of it, or through a dangling one."""

    def _victim(self, outside: str) -> Path:
        victim = Path(outside, "victim.txt")
        victim.write_text("keep\n", encoding="utf-8", newline="\n")
        return victim

    def test_gen_does_not_write_through_a_link_out_of_the_repo(self) -> None:
        with tempfile.TemporaryDirectory() as outside, TempRepo(SRC) as r:
            self.assertEqual(r.cli("init")[0], 0)
            victim = self._victim(outside)
            gen = r.root / "docs" / "codemap" / "_generated"
            gen.mkdir(parents=True, exist_ok=True)
            for f in gen.iterdir():
                f.unlink()
            _symlink(str(victim), gen / "fanin.md")
            self.assertEqual(r.json("gen", expect=2)["error"]["code"], "REFUSED")
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")

    def test_gen_does_not_write_into_a_linked_folder_out_of_the_repo(self) -> None:
        import shutil

        with tempfile.TemporaryDirectory() as outside, TempRepo(SRC) as r:
            self.assertEqual(r.cli("init")[0], 0)
            shutil.rmtree(r.root / "docs" / "codemap" / "_generated", ignore_errors=True)
            _symlink(outside, r.root / "docs" / "codemap" / "_generated")
            self.assertEqual(r.json("gen", expect=2)["error"]["code"], "REFUSED")
            self.assertEqual(os.listdir(outside), [])

    def test_init_treats_a_dangling_link_as_an_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as outside, TempRepo(SRC) as r:
            _symlink(str(Path(outside, "planted.toml")), r.root / "topomark.toml")
            _symlink(str(Path(outside, "planted.md")), r.root / "docs")
            self.assertEqual(r.json("init", expect=2)["error"]["code"], "REFUSED")
            self.assertEqual(r.json("init", "--force", expect=2)["error"]["code"], "REFUSED")
            self.assertEqual(os.listdir(outside), [])

    def test_stamps_file_linked_out_of_the_repo_is_neither_read_nor_written(self) -> None:
        with tempfile.TemporaryDirectory() as outside, TempRepo(SRC) as r:
            self.assertEqual(r.cli("init")[0], 0)
            victim = Path(outside, "elsewhere.json")
            victim.write_text('{"version": 2, "units": {}, "areas": {}, "token": "x"}\n', encoding="utf-8")
            stamps = r.root / "docs" / "codemap" / "stamps.json"
            if stamps.exists():
                stamps.unlink()
            _symlink(str(victim), stamps)
            self.assertEqual(r.json("stamp", "--baseline", expect=2)["error"]["code"], "REFUSED")
            self.assertIn('"token"', victim.read_text(encoding="utf-8"))

    def test_write_through_a_link_inside_the_repo_still_works(self) -> None:
        from topomark.errors import TopomarkError
        from topomark.repo import write_text

        with TempRepo(SRC) as r:
            (r.root / "docs").mkdir()
            (r.root / "docs" / "real.md").write_text("old\n", encoding="utf-8")
            _symlink("real.md", r.root / "docs" / "alias.md")
            write_text(r.root, "docs/alias.md", "new\n")
            self.assertEqual(r.read("docs/real.md"), "new\n")
            self.assertTrue((r.root / "docs" / "alias.md").is_symlink())
            _symlink("missing.md", r.root / "docs" / "dangling.md")
            with self.assertRaises(TopomarkError):
                write_text(r.root, "docs/dangling.md", "x\n")
            self.assertFalse((r.root / "docs" / "missing.md").exists())


class HostileFileTests(unittest.TestCase):
    """One file built to exhaust a parser must not end every whole-repo command."""

    DEEP = 100_000

    def test_deeply_nested_data_files_are_read_as_plain_text(self) -> None:
        files = {**SRC, "deep.json": "[" * self.DEEP + "]" * self.DEEP + "\n",
                 "deep.toml": "a = " + "[" * self.DEEP + "]" * self.DEEP + "\n",
                 "pkg/package.json": '{"name": "x", "dependencies": ' + "[" * self.DEEP + "]" * self.DEEP + "}\n"}
        with TempRepo(files) as r:
            for argv in (["map"], ["search", "run"], ["find", "run"], ["gen"]):
                with self.subTest(argv=argv):
                    rc, out, err = r.cli(*argv)
                    self.assertIn(rc, (0, 1), err)
            # deep.toml is beyond tomllib; whether deep.json parses depends on the interpreter's stack
            bad = {p["path"] for p in r.json("syntax", "deep.json", "deep.toml", expect=1)["problems"]}
            self.assertIn("deep.toml", bad)
            self.assertLessEqual(bad, {"deep.json", "deep.toml"})


class RepoGitConfigTests(unittest.TestCase):
    """A repository handed over with its .git (an archive, a shared folder) carries a .git/config
    that can name programs for git to run."""

    def _hook(self, outside: str) -> Path:
        if os.name == "nt":
            raise unittest.SkipTest("the planted program is a shell script")
        script = Path(outside, "planted.sh")
        script.write_text(f"#!/bin/sh\ntouch '{Path(outside, 'RAN')}'\ncat \"$@\" 2>/dev/null\n",
                          encoding="utf-8", newline="\n")
        script.chmod(0o755)
        return script

    def test_fsmonitor_from_the_repo_config_never_runs(self) -> None:
        for argv in (["outline", "."], ["tests-for", "--diff"], ["changes"], ["check"]):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as outside, TempRepo(SRC) as r:
                r.git("config", "core.fsmonitor", str(self._hook(outside)))
                r.write({"src/app.py": "def run():\n    return 2\n"})
                r.cli(*argv)
                self.assertFalse(Path(outside, "RAN").exists())

    def test_hook_does_not_install_into_a_hooks_path_outside_the_repo(self) -> None:
        with tempfile.TemporaryDirectory() as outside, TempRepo(SRC) as r:
            Path(outside, "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
            r.git("config", "core.hooksPath", outside)
            for action in ("install", "uninstall"):
                with self.subTest(action=action):
                    self.assertEqual(r.json("hook", action, expect=2)["error"]["code"], "REFUSED")
            self.assertEqual(os.listdir(outside), ["pre-commit"])
            self.assertEqual(r.json("hook", "status")["state"], "other hook present")
            r.git("config", "core.hooksPath", (r.root / ".git" / "hooks").as_posix())  # not a developer's global one
            self.assertEqual(r.json("hook", "install")["state"], "installed")
            self.assertTrue((r.root / ".git" / "hooks" / "pre-commit").is_file())

    def test_textconv_from_the_repo_config_never_runs(self) -> None:
        with tempfile.TemporaryDirectory() as outside, TempRepo({**SRC, ".gitattributes": "*.py diff=planted\n"}) as r:
            r.git("config", "diff.planted.textconv", str(self._hook(outside)))
            r.write({"src/app.py": "def run():\n    return 2\n"})
            self.assertEqual(r.cli("changes")[0], 0)
            self.assertFalse(Path(outside, "RAN").exists())


PLANT = ("import pathlib\npathlib.Path(__file__).with_name('PWNED').write_text('x')\n"
         "raise ImportError('planted module was imported')\n")


class LauncherTests(unittest.TestCase):
    """The plugin hooks start topomark inside whatever repository the agent opened. A module planted
    at that repository's root must never shadow the standard library."""

    def _assert_not_imported(self, argv: list[str], env: dict[str, str]) -> None:
        import subprocess

        with TempRepo({**SRC, "tomllib.py": PLANT, "json.py": PLANT}) as r:
            proc = subprocess.run(argv, cwd=r.root, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertFalse((r.root / "PWNED").exists(), proc.stderr)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("topomark", proc.stdout)

    def test_module_in_the_working_directory_is_not_imported(self) -> None:
        import sys

        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        self._assert_not_imported([sys.executable, "-P", "-m", "topomark", "--version"], env)

    def test_worker_processes_do_not_import_it_either(self) -> None:
        """A first whole-repo command on a large repository parses in worker processes: new
        interpreters, started in the repository. They must not find the planted module."""
        import subprocess
        import sys

        from topomark.index import PARALLEL_MIN

        files = {f"src/m{k:04d}.py": f"def f{k}():\n    return {k}\n" for k in range(PARALLEL_MIN + 20)}
        src = str(Path(__file__).resolve().parents[1] / "src")
        with TempRepo({**files, "tomllib.py": PLANT, "json.py": PLANT}) as r, tempfile.TemporaryDirectory() as cache:
            env = {**os.environ, "PYTHONPATH": src, "TOPOMARK_CACHE": cache, "TOPOMARK_JOBS": "2"}
            argv = [sys.executable, "-P", "-m", "topomark", "map", "--tokens", "200"]
            proc = subprocess.run(argv, cwd=r.root, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((r.root / "PWNED").exists(), proc.stderr)
            # the same run without -P does import it: the check above can fail
            argv.remove("-P")
            subprocess.run(argv, cwd=r.root, env={**env, "TOPOMARK_CACHE": cache + "-2"}, capture_output=True)
            self.assertTrue((r.root / "PWNED").exists())

    def test_a_shim_for_a_version_that_is_not_active_is_passed_over(self) -> None:
        """pyenv and asdf put a `python3.14` on PATH for every installed version; it exits 127 when
        that version is not the active one. The launcher must move on to an interpreter that runs."""
        import subprocess
        import sys

        if os.name == "nt":
            raise unittest.SkipTest("bin/topomark is a bash script")
        launcher = Path(__file__).resolve().parents[1] / "bin" / "topomark"
        with tempfile.TemporaryDirectory() as tmp:
            shims, real = Path(tmp, "shims"), Path(tmp, "real")
            shims.mkdir()
            real.mkdir()
            for name in ("python3.14", "python3.13", "python3.12", "python3.11"):
                shim = shims / name
                shim.write_text("#!/bin/sh\necho \"pyenv: $0: command not found\" >&2\nexit 127\n", encoding="utf-8")
                shim.chmod(0o755)
            os.symlink(sys.executable, real / "python3")
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            env["PATH"] = os.pathsep.join([str(shims), str(real), "/usr/bin", "/bin"])
            proc = subprocess.run(["bash", str(launcher), "--version"], env=env, capture_output=True, text=True,
                                  encoding="utf-8")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("topomark", proc.stdout)

    def test_launcher_keeps_the_working_directory_off_sys_path(self) -> None:
        launcher = Path(__file__).resolve().parents[1] / "bin" / "topomark"
        self.assertIn('exec "$PY" -P -m topomark', launcher.read_text(encoding="utf-8"))
        if os.name == "nt":
            raise unittest.SkipTest("bin/topomark is a bash script")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        self._assert_not_imported(["bash", str(launcher), "--version"], env)


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
            # the template is the repository's own text: say where it came from
            self.assertEqual(r.json("tests-for", "src/app.py")["commands"][0]["source"], "topomark.toml")
            self.assertIn("command from topomark.toml", r.cli("tests-for", "src/app.py")[1])

    def test_path_starting_with_a_dash_is_not_an_option(self) -> None:
        from topomark.runners import fill_template as fill

        self.assertEqual(fill("pytest {file}", {"file": "-k.py"}), "pytest ./-k.py")
        self.assertEqual(fill("pytest {files}", {"files": ["-x.py", "a.py"]}), "pytest ./-x.py a.py")
        self.assertEqual(fill("python -m unittest {names}", {"names": ["--failfast.py"]}),
                         "python -m unittest ./--failfast.py")
        self.assertEqual(fill("pytest {file}::{class}", {"file": "a.py", "class": "T"}), "pytest a.py::T")

    def test_template_quotes_and_empty_placeholders(self) -> None:
        from topomark.runners import fill_template as fill

        self.assertEqual(fill('t -f "{names}"', {"names": ["A.b", "x$y"]}, "|"), 't -f "A.b|x\\$y"')
        self.assertEqual(fill("t '{file}'", {"file": "it's.py"}), "t 'it'\\''s.py'")
        self.assertEqual(fill("pytest {file}::{class}::{method}", {"file": "a b.py", "class": "", "method": "m"}),
                         "pytest 'a b.py'::m")


if __name__ == "__main__":
    unittest.main()
