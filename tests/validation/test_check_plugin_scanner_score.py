"""Guards for the plugin scanner score gate.

The scanner itself is not run here (about 50s and a network install); every
test replaces the subprocess boundary or uses a throwaway git repository.

Coverage:

- positive: a report at or above the minimum exits 0 and prints the score and
  examined package count; ``export_ref`` writes the committed tree.
- negative: a report below the minimum exits 1 and names each check that lost
  points; a missing report, a scanner timeout, a missing ``uv``, a report with
  no integer score, and unreadable JSON exit 3; a bad ref, a directory outside
  git, and a bad argument exit 2.
- edge: ``export_ref`` leaves untracked files out, a score equal to the minimum
  passes, and a report with no categories still summarizes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_VALIDATION_DIR = REPO_ROOT / "scripts" / "validation"
if str(_VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(_VALIDATION_DIR))

import check_plugin_scanner_score as gate


def _report(score: object, lost: int = 0) -> dict[str, object]:
    return {
        "score": score,
        "packages": [{"name": "a"}, {"name": "b"}],
        "categories": [
            {
                "name": "[claude:.] Security",
                "checks": [
                    {
                        "name": "SECURITY.md found",
                        "points": 3 - lost,
                        "maxPoints": 3,
                        "message": "m",
                    },
                    {"name": "LICENSE found", "points": 3, "maxPoints": 3, "message": "ok"},
                ],
            }
        ],
    }


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "tracked.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "init")
    (repo / "untracked.txt").write_text("y", encoding="utf-8")
    monkeypatch.chdir(repo)
    return repo


def _fake_scanner(monkeypatch: pytest.MonkeyPatch, report: object) -> None:
    def write_report(_root: Path, _tree: Path, path: Path) -> None:
        path.write_text(json.dumps(report), encoding="utf-8")

    monkeypatch.setattr(gate, "run_scanner", write_report)


def test_score_at_minimum_passes(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_scanner(monkeypatch, _report(80))
    assert gate.main([]) == 0
    assert "score=80 min=80 ref=HEAD packages=2" in capsys.readouterr().out


def test_score_below_minimum_fails_and_names_lost_checks(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_scanner(monkeypatch, _report(54, lost=3))
    assert gate.main([]) == 1
    err = capsys.readouterr().err
    assert "-3  [claude:.] Security: SECURITY.md found (m)" in err
    assert "LICENSE found" not in err
    assert "score 54 is below 80" in err


def test_min_score_flag_moves_the_bar(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_scanner(monkeypatch, _report(80))
    assert gate.main(["--min-score", "81"]) == 1


@pytest.mark.parametrize("report", [_report(None), _report("80"), ["not", "an", "object"]])
def test_malformed_report_is_external_error(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, report: object
) -> None:
    _fake_scanner(monkeypatch, report)
    assert gate.main([]) == 3


def test_unreadable_report_is_external_error(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def write_garbage(_root: Path, _tree: Path, path: Path) -> None:
        path.write_text("{not json", encoding="utf-8")

    monkeypatch.setattr(gate, "run_scanner", write_garbage)
    assert gate.main([]) == 3


def test_scanner_without_report_is_external_error(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def crashed(args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "uv":
            return subprocess.CompletedProcess(args, 1, b"", b"Traceback: boom")
        return subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, check=False)

    monkeypatch.setattr(gate, "_run", crashed)
    assert gate.main([]) == 3
    assert "wrote no report (exit 1): Traceback: boom" in capsys.readouterr().err


def test_scanner_timeout_is_external_error(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def slow(args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "uv":
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, check=False)

    monkeypatch.setattr(gate, "_run", slow)
    assert gate.main([]) == 3
    assert f"{gate.SCAN_BUDGET_SECONDS}s budget" in capsys.readouterr().err


def test_missing_uv_is_external_error(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_uv(args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
        if args[0] == "uv":
            raise FileNotFoundError("uv")
        return subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, check=False)

    monkeypatch.setattr(gate, "_run", no_uv)
    assert gate.main([]) == 3


def test_scanner_command_uses_the_pinned_project(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def record(args: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(gate, "_run", record)
    report = git_repo / "r.json"
    report.write_text("{}", encoding="utf-8")
    gate.run_scanner(git_repo, git_repo / "tree", report)
    command = seen[0]
    assert command[:3] == ["uv", "run", "--project"]
    assert command[3].endswith("build/plugin-scanner")
    assert "--frozen" in command
    assert command[command.index("--fail-on-severity") + 1] == "none"
    assert "--config" not in command


def test_bad_ref_is_config_error(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert gate.main(["--ref", "no-such-ref"]) == 2
    assert "cannot export ref 'no-such-ref'" in capsys.readouterr().err


def test_outside_git_is_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert gate.main([]) == 2


def test_bad_argument_is_config_error() -> None:
    assert gate.main(["--min-score", "eighty"]) == 2


def test_export_ref_writes_only_the_committed_tree(git_repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    gate.export_ref(git_repo, "HEAD", out)
    assert (out / "tracked.txt").read_text(encoding="utf-8") == "x"
    assert not (out / "untracked.txt").exists()


def test_summarize_tolerates_missing_categories() -> None:
    assert gate.summarize({"score": 90}) == (90, 0, [])


def test_summarize_rejects_a_missing_score() -> None:
    with pytest.raises(gate.GateError) as exc:
        gate.summarize({})
    assert exc.value.exit_code == 3


def test_scanner_project_lock_pins_the_action_wheel() -> None:
    """The local lock must carry the wheel hash the CI action verifies."""
    lock = (REPO_ROOT / gate.SCANNER_PROJECT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "plugin-scanner"\nversion = "3.0.123"' in lock
    assert "d176d4d35c980e4e66c9e72bd79d0a100efbf40bea9d5f4dae35c8609eb7d04d" in lock
    workflow = (REPO_ROOT / ".github" / "workflows" / "plugin-scanner.yml").read_text(
        encoding="utf-8"
    )
    assert "ai-plugin-scanner-action@caba2e96aa8ad2feb6cf6fca52442b52e22e779f" in workflow
    assert "min_score: 80" in workflow
