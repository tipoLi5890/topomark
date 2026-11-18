#!/usr/bin/env python3
"""Time topomark's navigation and code-map commands on a synthetic repo (``tools/synth_repo.py``).

    python3 tools/bench_nav.py                      # generate 3,000 files in a temp dir
    python3 tools/bench_nav.py --repo DIR --runs 5  # reuse a repo synth_repo.py made
    python3 tools/bench_nav.py --profile OUT_DIR    # also cProfile each warm command

Every timing is a subprocess (``python3 -m topomark ...`` with ``PYTHONPATH`` set
to ``--src``), so interpreter start-up and imports are included, as an agent sees
them. The cache is a fresh temporary ``TOPOMARK_CACHE``: one cold ``map`` fills it,
then each case runs ``--runs`` times warm; the table shows min and median wall
time and the median CPU time (user + system) of the child, which stays meaningful
on a busy machine where wall time mostly measures waiting. ``--profile`` writes
``<case>.prof`` and the top functions by cumulative time (``<case>.txt``) for one
more warm run of each case.

The ``hook-*`` cases run ``agent-hook`` the way the Claude Code plugin does: the hook
payload on stdin, a new ``session_id`` every run, so ``pre-read`` always takes its
first-read path (counts the lines, writes the once-per-session marker, prints hints).
A hook exits 0 and stays silent whatever goes wrong, so a broken hook would time
fine; each run's stdout is checked as well. ``session-start`` must print its
pointer, ``pre-read`` on the monolith the outline hint, ``post-edit`` on the
monolith nothing (it parses), and ``hook-post-edit-broken`` must report the file.
That last case runs in a scratch one-file repo (the monolith committed, then
broken in the work tree), so nothing is written into ``--repo``. A case that fails
its check is marked FAIL, the reason (and the ``--debug`` traceback, if any) goes
to stderr, and the bench exits 1.

The code-map cases (``check``, ``stale``, ``gen``, ``changes``) need a code map and a change to
find, so they run in a scratch copy of the repo: ``init``, ``draft --write`` per area, ``gen``,
``sync`` and ``stamp --baseline`` there, a commit, then one new method on ``CoreHub`` in the work
tree. ``check`` and ``stale`` must report that file's unit and nothing else, or the case is marked FAIL.

The cases name files that exist in every synthetic repo, so ``--repo`` must point
at one made by ``synth_repo.py``. Stdlib only; never touches the user's cache.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import pstats
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

CASES: list[tuple[str, list[str]]] = [
    ("map", ["map", "--tokens", "1500"]),
    ("impact-file", ["impact", "py/core/hub.py"]),
    ("impact-symbol", ["impact", "CoreHub"]),
    ("tests-for", ["tests-for", "py/chain/leaf.py"]),
    ("outline-big", ["outline", "py/big/monolith.py"]),
    ("outline-small", ["outline", "py/chain/leaf.py"]),
    ("symbol", ["symbol", "py/chain/top.py#ChainTop"]),
    ("search", ["search", "invoice", "payment", "service"]),
    ("brief-file", ["brief", "py/core/hub.py"]),
    ("brief-symbol", ["brief", "CoreHub"]),
    ("locate", ["locate", "Process-wide registry of named counters"]),
]
# in a scratch copy with a code map and one changed interface (see _codemap_repo)
HUB = "py/core/hub.py"
CODEMAP_CASES: list[tuple[str, list[str]]] = [
    ("check", ["check"]),
    ("stale", ["stale"]),
    ("gen", ["gen"]),
    ("changes", ["changes"]),
]
HUB_EDIT = "\n    def reset(self) -> None:\n        self.counters.clear()\n"  # appended: a new public method

BIG = "py/big/monolith.py"
# (case, agent-hook action, repo file in the payload's tool_input or "", what the hook must print:
# None = nothing; otherwise a hook answer whose additionalContext contains each of these words)
HOOK_CASES: list[tuple[str, str, str, list[str] | None]] = [
    ("hook-session", "session-start", "", ["topomark"]),
    ("hook-pre-read", "pre-read", BIG, [BIG, "outline"]),
    ("hook-post-edit", "post-edit", BIG, None),
]
# post-edit on a file that no longer parses, in a scratch repo (see _broken_repo)
BROKEN_CASE: tuple[str, str, str, list[str] | None] = ("hook-post-edit-broken", "post-edit", BIG, [BIG, "syntax"])
BREAK = "\n\ndef broken(:\n    pass\n"  # appended to the scratch copy: a Python syntax error


def _synth_repo() -> Any:
    """``tools/synth_repo.py`` (``tools/`` goes on ``sys.path`` once; it is already there in a script run)."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import synth_repo

    return synth_repo


def _hook_payload(repo: Path, path: str) -> str:
    payload: dict = {"session_id": uuid.uuid4().hex, "cwd": str(repo), "source": "startup"}
    if path:
        payload["tool_input"] = {"file_path": str(repo / path)}
    return json.dumps(payload)


def hook_problem(stdout: str, must: list[str] | None) -> str:
    """Why a hook's stdout is not what its case expects, "" when it is: ``must`` None = silence,
    else a hook-protocol object whose ``additionalContext`` contains every word in ``must``."""
    text = stdout.strip()
    if must is None:
        return f"expected no output, got {text[:200]!r}" if text else ""
    if not text:
        return "printed nothing"
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    out = data.get("hookSpecificOutput") if isinstance(data, dict) else None
    context = out.get("additionalContext") if isinstance(out, dict) else None
    if not isinstance(context, str) or not context.strip():
        return f"not a hook answer with additionalContext: {text[:200]!r}"
    missing = [w for w in must if w not in context]
    return f"the hint lacks {missing}: {context[:200]!r}" if missing else ""


def _env(src: Path, cache: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["TOPOMARK_CACHE"] = str(cache)
    env["PYTHONUTF8"] = "1"
    return env


def _cpu() -> float:
    try:
        import resource
    except ImportError:  # Windows
        return 0.0
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime


def _run(argv: list[str], repo: Path, env: dict[str, str], stdin: str | None = None) -> tuple[float, float, str]:
    """(wall seconds, child CPU seconds, stdout) of one run."""
    c0, t0 = _cpu(), time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "topomark", "-C", str(repo), *argv], env=env, input=stdin,
                       capture_output=True, text=True, encoding="utf-8")
    dt, dc = time.perf_counter() - t0, _cpu() - c0
    if p.returncode not in (0, 1):
        raise SystemExit(f"bench: {' '.join(argv)} exited {p.returncode}\n{p.stderr}")
    return dt, dc, p.stdout


def _debug_tail(argv: list[str], repo: Path, env: dict[str, str], stdin: str) -> str:
    """The last lines of stderr from one more run with ``--debug``, which lets a hook's exception through."""
    p = subprocess.run([sys.executable, "-m", "topomark", "-C", str(repo), "--debug", *argv], env=env, input=stdin,
                       capture_output=True, text=True, encoding="utf-8")
    tail = p.stderr.strip().splitlines()[-12:]
    if not tail:
        return " (a --debug run raised nothing either)"
    return "\n    --debug stderr:\n      " + "\n      ".join(tail)


def _timing(name: str, argv: list[str], got: list[tuple[float, float]]) -> dict:
    wall = [w for w, _ in got]
    return {"case": name, "argv": argv, "min": round(min(wall), 3), "median": round(statistics.median(wall), 3),
            "cpu": round(statistics.median(c for _, c in got), 3)}


def _time_hook(case: tuple[str, str, str, list[str] | None], repo: Path, env: dict[str, str], runs: int,
               shown: str = "") -> dict:
    name, action, path, must = case
    argv = ["agent-hook", action]
    got: list[tuple[float, float]] = []
    problem = ""
    for _ in range(max(1, runs)):
        wall, cpu, out = _run(argv, repo, env, _hook_payload(repo, path))
        got.append((wall, cpu))
        problem = problem or hook_problem(out, must)
    if problem:
        problem += _debug_tail(argv, repo, env, _hook_payload(repo, path))
    row = _timing(name, argv + ([f"<{shown or path}>"] if path else []), got)
    row["check"] = problem or "ok"
    return row


def _broken_repo(repo: Path, where: Path, path: str) -> Path:
    """A one-file git repo at ``where``: ``path`` copied from ``repo`` and committed, then broken in the
    work tree, so post-edit takes its finding path (HEAD parses, the edit does not) without a write to ``repo``."""
    full = where / path
    full.parent.mkdir(parents=True, exist_ok=True)
    with open(repo / path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    _synth_repo().commit_all(where, "bench: post-edit baseline")
    with open(full, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(BREAK)
    return where


def bench_hooks(repo: Path, env: dict[str, str], runs: int, scratch: Path) -> list[dict]:
    """Time and check each hook case; the broken-file case runs in a scratch repo made under ``scratch``."""
    rows = [_time_hook(case, repo, env, runs) for case in HOOK_CASES]
    broken = _broken_repo(repo, scratch, BROKEN_CASE[2])
    rows.append(_time_hook(BROKEN_CASE, broken, env, runs, shown=f"{BROKEN_CASE[2]}, broken, one-file repo"))
    return rows


def _codemap_repo(repo: Path, where: Path, env: dict[str, str]) -> Path:
    """A copy of ``repo`` at ``where`` with a baselined code map, committed, and ``HUB`` given one
    more method in the work tree: what ``check``, ``stale`` and ``changes`` are for. Nothing is
    written into ``repo``."""
    import shutil

    shutil.copytree(repo, where, symlinks=True)
    areas = [a["name"] for a in json.loads(_run(["init", "--json"], where, env)[2])["areas"]]
    for area in areas:
        _run(["draft", area, "--write"], where, env)
    for step in (["gen"], ["sync"], ["stamp", "--baseline"]):
        _run(step, where, env)
    _synth_repo().commit_all(where, "bench: code map")
    with open(where / HUB, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(HUB_EDIT)
    return where


def _holds_hub(unit: object) -> bool:
    """Is ``unit`` the hub file, or (a large area has directory units) a directory it is in?"""
    return isinstance(unit, str) and (unit == HUB or (unit.endswith("/") and HUB.startswith(unit)))


def codemap_problem(name: str, stdout: str) -> str:
    """Why a code-map case did not see the one changed interface, "" when it did."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return f"not JSON: {stdout[:200]!r}"
    if name == "check":
        got = [(p["code"], p.get("subject")) for p in data.get("problems", [])]
        ok = len(got) == 1 and got[0][0] == "STAMP_CHANGED" and _holds_hub(got[0][1])
        return "" if ok else f"expected one STAMP_CHANGED for {HUB}, got {got[:5]}"
    if name == "stale":
        got = [p.get("subject") for p in data.get("needs_review", [])]
        return "" if len(got) == 1 and _holds_hub(got[0]) else f"expected {HUB} to need review, got {got[:5]}"
    if name == "changes":
        got = [f["path"] for f in data.get("files", [])]
        return "" if got == [HUB] else f"expected {HUB} as the one changed file, got {got[:5]}"
    return ""


def bench_codemap(repo: Path, env: dict[str, str], runs: int, scratch: Path) -> list[dict]:
    """Time and check each code-map case in a scratch copy made under ``scratch``."""
    where = _codemap_repo(repo, scratch, env)
    _run(["check"], where, env)  # fills the cache for the copy: the cases are timed warm, like the others
    rows = []
    for name, argv in CODEMAP_CASES:
        got: list[tuple[float, float]] = []
        problem = ""
        for _ in range(max(1, runs)):
            wall, cpu, out = _run([*argv, "--json"], where, env)
            got.append((wall, cpu))
            problem = problem or codemap_problem(name, out)
        row = _timing(name, argv, got)
        row["check"] = problem or "ok"
        rows.append(row)
    return rows


def _profile(name: str, argv: list[str], repo: Path, env: dict[str, str], out: Path) -> None:
    prof = out / f"{name}.prof"
    subprocess.run([sys.executable, "-m", "cProfile", "-o", str(prof), "-m", "topomark", "-C", str(repo), *argv],
                   env=env, capture_output=True, check=False)
    buf = io.StringIO()
    stats = pstats.Stats(str(prof), stream=buf)
    stats.sort_stats("cumulative").print_stats(30)
    stats.sort_stats("tottime").print_stats(20)
    with open(out / f"{name}.txt", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(buf.getvalue())


def bench(repo: Path, src: Path, runs: int, profile: Path | None) -> dict:
    with tempfile.TemporaryDirectory(prefix="topomark-bench-") as tmp:
        cache = Path(tmp) / "cache"
        cache.mkdir()
        env = _env(src, cache)
        cold, cold_cpu, _ = _run(["map", "--tokens", "1500"], repo, env)
        rows = []
        for name, argv in CASES:
            rows.append(_timing(name, argv, [_run(argv, repo, env)[:2] for _ in range(max(1, runs))]))
        rows += bench_codemap(repo, env, runs, Path(tmp) / "codemap")
        rows += bench_hooks(repo, env, runs, Path(tmp) / "broken")
        if profile is not None:
            profile.mkdir(parents=True, exist_ok=True)
            for name, argv in CASES:
                _profile(name, argv, repo, env, profile)
    files = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True,
                           encoding="utf-8").stdout.count("\n")
    return {"repo": str(repo), "src": str(src), "files": files, "runs": runs, "cold_map": round(cold, 3),
            "cold_map_cpu": round(cold_cpu, 3), "cases": rows,
            "failed": [r["case"] for r in rows if r.get("check", "ok") != "ok"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", type=Path, help="a repo made by synth_repo.py (default: generate one)")
    ap.add_argument("--files", type=int, default=3000, help="size of the generated repo (default 3000)")
    ap.add_argument("--src", type=Path, default=ROOT / "src", help="topomark source dir to time (default: this checkout)")
    ap.add_argument("--runs", type=int, default=3, help="warm runs per case (default 3)")
    ap.add_argument("--profile", type=Path, metavar="DIR", help="write cProfile output per case here")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    args = ap.parse_args(argv)
    tmp = None
    repo = args.repo
    if repo is None:
        tmp = tempfile.TemporaryDirectory(prefix="topomark-synth-")
        repo = Path(tmp.name) / "repo"
        _synth_repo().generate(repo, args.files)
    try:
        result = bench(repo.resolve(), args.src.resolve(), args.runs, args.profile)
    finally:
        if tmp is not None:
            tmp.cleanup()
    for r in result["cases"]:
        if r.get("check", "ok") != "ok":
            sys.stderr.write(f"bench: FAIL {r['case']}: {r['check']}\n")
    if args.json:
        print(json.dumps(result, indent=1))
        return 1 if result["failed"] else 0
    print(f"{result['files']} files, src {result['src']}, {result['runs']} warm runs per case")
    print(f"cold map --tokens 1500: {result['cold_map']:.2f} s wall, {result['cold_map_cpu']:.2f} s CPU")
    print(f"{'case':<22} {'min s':>7} {'median s':>9} {'CPU s':>7}  command")
    for r in result["cases"]:
        fail = "" if r.get("check", "ok") == "ok" else "  FAIL"
        print(f"{r['case']:<22} {r['min']:>7.2f} {r['median']:>9.2f} {r['cpu']:>7.2f}  "
              f"topomark {' '.join(r['argv'])}{fail}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
