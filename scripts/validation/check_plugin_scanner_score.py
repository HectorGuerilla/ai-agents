#!/usr/bin/env python3
"""Gate: the HOL AI plugin scanner scores this repository at least 80.

hashgraph-online/awesome-ai-plugins lists a plugin only after its centralized
source scan completes with a normalized score of 80 or more (its
SCANNER_GUIDE.md). That scan clones the default branch and scores the whole
tree, so one new file anywhere can drop the listing below the bar. This gate
runs the same scanner version locally, before a push, and
``.github/workflows/plugin-scanner.yml`` runs the pinned action in CI.

What is scanned: the tree of a named ref (``HEAD`` by default), exported with
``git archive`` into a temporary directory. A directory walk of the checkout
would also score untracked files, caches, and virtualenvs that a fresh clone
never has, so the same commit could pass here and fail in the catalog
(.claude/rules/ci-scripts.md item 9).

Which scanner: ``build/plugin-scanner/uv.lock`` pins ``plugin-scanner`` by hash
to the version the CI action verifies, and ``uv run --frozen`` installs exactly
that. Repository scanner config (``.plugin-scanner.toml``) is never read: the
catalog runs with ``trust_repository_policy`` false, so a suppression would
raise only the local score.

The scanner run is bounded by ``SCAN_BUDGET_SECONDS``, below the lefthook cap,
so a slow run ends with exit 3 and a reason instead of a lefthook kill.

CLI::

    uv run --frozen python scripts/validation/check_plugin_scanner_score.py \
        [--ref HEAD] [--min-score 80]

Exit codes (ADR-035):
    0 - Score at or above the minimum (prints score and examined packages)
    1 - Score below the minimum (prints each check that lost points)
    2 - Config error (not in a git work tree, bad ref, bad argument)
    3 - External error (scanner missing, crashed, timed out, or wrote no report)
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

DEFAULT_MIN_SCORE = 80
SCAN_BUDGET_SECONDS = 150
GIT_TIMEOUT_SECONDS = 60
SCANNER_PROJECT = Path("build") / "plugin-scanner"

_OK = 0
_BELOW = 1
_CONFIG_ERROR = 2
_EXTERNAL_ERROR = 3


class GateError(Exception):
    """A failure that stops the gate before a score exists."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _run(args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, check=False)


def _repo_root() -> Path:
    """Return the work tree root, after confirming cwd is inside it."""
    try:
        result = _run(["git", "rev-parse", "--show-toplevel"], Path.cwd(), GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"cannot run git: {exc}", _CONFIG_ERROR) from exc
    if result.returncode != 0:
        raise GateError("not inside a git work tree", _CONFIG_ERROR)
    root = Path(result.stdout.decode("utf-8").strip()).resolve()
    if not Path.cwd().resolve().is_relative_to(root):
        raise GateError(f"cwd is outside the resolved work tree {root}", _CONFIG_ERROR)
    return root


def export_ref(repo_root: Path, ref: str, destination: Path) -> None:
    """Write the tree of ``ref`` into ``destination`` via ``git archive``."""
    try:
        result = _run(["git", "archive", "--format=tar", ref], repo_root, GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"git archive {ref} failed: {exc}", _EXTERNAL_ERROR) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GateError(f"cannot export ref {ref!r}: {detail}", _CONFIG_ERROR)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(destination, filter="data")


def run_scanner(repo_root: Path, tree: Path, report: Path) -> None:
    """Run the pinned scanner over ``tree`` and write its JSON report."""
    args = [
        "uv",
        "run",
        "--project",
        str(repo_root / SCANNER_PROJECT),
        "--frozen",
        "--quiet",
        "plugin-scanner",
        "scan",
        str(tree),
        "--format",
        "json",
        "--output",
        str(report),
        "--fail-on-severity",
        "none",
    ]
    try:
        result = _run(args, repo_root, SCAN_BUDGET_SECONDS)
    except FileNotFoundError as exc:
        raise GateError("uv is not installed; see build/plugin-scanner", _EXTERNAL_ERROR) from exc
    except subprocess.TimeoutExpired as exc:
        msg = f"scanner exceeded its {SCAN_BUDGET_SECONDS}s budget"
        raise GateError(msg, _EXTERNAL_ERROR) from exc
    if not report.is_file():
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-2000:]
        msg = f"scanner wrote no report (exit {result.returncode}): {detail}"
        raise GateError(msg, _EXTERNAL_ERROR)


def summarize(report: dict[str, object]) -> tuple[int, int, list[str]]:
    """Return ``(score, packages examined, lines naming each check that lost points)``."""
    score = report.get("score")
    if not isinstance(score, int):
        raise GateError(f"report has no integer score (got {score!r})", _EXTERNAL_ERROR)
    packages = report.get("packages")
    examined = len(packages) if isinstance(packages, list) else 0
    lost: list[str] = []
    categories = report.get("categories")
    for category in categories if isinstance(categories, list) else []:
        if not isinstance(category, dict):
            continue
        for check in category.get("checks") or []:
            if not isinstance(check, dict):
                continue
            points, max_points = check.get("points", 0), check.get("maxPoints", 0)
            if isinstance(points, int) and isinstance(max_points, int) and points < max_points:
                lost.append(
                    f"  -{max_points - points:<2} {category.get('name')}: "
                    f"{check.get('name')} ({check.get('message')})"
                )
    return score, examined, lost


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="HEAD", help="git ref whose tree is scanned")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return _CONFIG_ERROR if exc.code else _OK
    try:
        repo_root = _repo_root()
        with tempfile.TemporaryDirectory(prefix="plugin-scanner-") as work:
            tree = Path(work) / "tree"
            report_path = Path(work) / "report.json"
            export_ref(repo_root, args.ref, tree)
            run_scanner(repo_root, tree, report_path)
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise GateError(f"unreadable scanner report: {exc}", _EXTERNAL_ERROR) from exc
            if not isinstance(report, dict):
                raise GateError("scanner report is not a JSON object", _EXTERNAL_ERROR)
            score, examined, lost = summarize(report)
    except GateError as exc:
        print(f"plugin-scanner: {exc}", file=sys.stderr)
        return exc.exit_code

    print(f"plugin-scanner: score={score} min={args.min_score} ref={args.ref} packages={examined}")
    if score >= args.min_score:
        return _OK
    print("Checks that lost points:", file=sys.stderr)
    for line in lost:
        print(line, file=sys.stderr)
    print(
        f"plugin-scanner: score {score} is below {args.min_score}; the "
        "awesome-ai-plugins listing requires 80 (SCANNER_GUIDE.md).",
        file=sys.stderr,
    )
    return _BELOW


if __name__ == "__main__":
    sys.exit(main())
