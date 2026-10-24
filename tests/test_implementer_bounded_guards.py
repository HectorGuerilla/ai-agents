"""Implementer prompts must not stop on an authorized, bounded guard (issue #6881).

The implementer stopped twice before a caller-authorized exclusion guard.
It demanded a plan file when the brief carried acceptance criteria, and it
demanded security approval before a change that only narrows what runs.
These tests pin the corrected stop conditions in every rendered copy.
"""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATHS = (
    PROJECT_ROOT / "templates/agents/implementer.shared.md",
    PROJECT_ROOT
    / "templates/agents/partials/implementer-blocking-read-project-documentation.mustache",
    PROJECT_ROOT / "templates/agents/partials/implementer-code-quality-standards.mustache",
    PROJECT_ROOT / "templates/agents/partials/implementer-degraded-mode-protocol.mustache",
    PROJECT_ROOT / "src/claude/agents/implementer.md",
    PROJECT_ROOT / ".claude/agents/implementer.md",
    PROJECT_ROOT / ".github/agents/implementer.agent.md",
    PROJECT_ROOT / "src/copilot-cli/agents/implementer.agent.md",
    PROJECT_ROOT / "src/cursor/agents/implementer.md",
    PROJECT_ROOT / "src/vs-code-agents/implementer.agent.md",
)
RENDERED_PATHS = PROMPT_PATHS[4:]
PLAN_PARTIAL, SECURITY_PARTIAL, HANDOFF_PARTIAL = PROMPT_PATHS[1:4]
FULL_PROMPTS = (PROMPT_PATHS[0], *RENDERED_PATHS)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", FULL_PROMPTS, ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
class TestFullPrompt:
    def test_brief_with_acceptance_criteria_counts_as_a_plan(self, path: Path) -> None:
        text = _text(path)

        assert "or from the caller's task brief" in text
        assert "Do not demand a plan file when the brief already carries them." in text

    def test_plan_block_fires_only_when_plan_and_brief_lack_criteria(self, path: Path) -> None:
        text = _text(path)

        assert (
            "only when neither the plan file nor the brief states any acceptance criteria"
        ) in text

    def test_restrictive_authorized_guard_is_implement_then_flag(self, path: Path) -> None:
        text = _text(path)

        assert "**Implement, then flag.**" in text
        assert "only narrows what runs and leaves every existing safeguard in place" in text
        assert "Do not ask for security approval first." in text

    def test_weakening_a_safeguard_still_stops_for_security_review(self, path: Path) -> None:
        text = _text(path)

        assert "**Stop before proceeding.**" in text
        assert "weaken, remove, or bypass an existing safeguard" in text
        assert 'Return to orchestrator with "SECURITY_FLAG: [what, where, risk]"' in text

    def test_new_security_mechanisms_still_stop_for_review(self, path: Path) -> None:
        text = _text(path)

        assert "widen a trust boundary, read or write credential values" in text
        assert (
            "add a new path-construction, command-construction, authentication, "
            "authorization, or secret-handling mechanism"
        ) in text
        assert "adds no new mechanism and does not alter a safeguard" in text
        assert "- **Implement, then flag.** Every other case." not in text

    def test_guard_exception_is_caller_authorized_and_bounded(self, path: Path) -> None:
        text = _text(path)

        assert "A caller-authorized, bounded change that only narrows what runs" in text
        assert "Escalate only when a Stop before proceeding condition above applies" in text

    def test_brief_counts_in_every_plan_stop(self, path: Path) -> None:
        text = _text(path)

        assert "A caller brief with acceptance criteria counts as the plan." in text
        assert (
            "Read the complete plan, from `.project-toolkit/planning/` or the caller's brief"
            in text
        )
        assert "per approved plan or caller brief" in text
        assert "outside the plan or brief" in text
        assert "Read complete plans from `.project-toolkit/planning/`" not in text

    def test_flagging_process_applies_only_when_not_stopped(self, path: Path) -> None:
        text = _text(path)

        assert "When ANY trigger matches and you did not stop:" in text
        assert "meets a Stop before proceeding condition in Security Flagging" in text

    def test_security_checks_stay_mandatory(self, path: Path) -> None:
        text = _text(path)

        assert "**Security pattern checks are NOT optional.**" in text
        assert "mandatory checks on every change" in text

    def test_unconditional_stop_wording_is_gone(self, path: Path) -> None:
        text = _text(path)

        assert "are mandatory blocking preconditions" not in text
        assert "When you touch sensitive surfaces, stop and flag." not in text
        assert "flag immediately:" not in text
        assert "If the plan has no acceptance criteria, stop and return" not in text
        assert (
            'Return to orchestrator with "SECURITY_FLAG: [what, where, risk]" and let'
            " security agent review before proceeding.\n\nDo not"
        ) not in text

    def test_handoff_codes_match_the_new_conditions(self, path: Path) -> None:
        text = _text(path)

        assert "No acceptance criteria in the plan file or the caller's brief" in text
        assert (
            "A surface you only touch gets a Security Flag note in a `[COMPLETE]` handoff" in text
        )


def test_partials_hold_the_fixes_that_rendered_copies_carry() -> None:
    assert "caller's task brief" in _text(PLAN_PARTIAL)
    assert "**Implement, then flag.**" in _text(SECURITY_PARTIAL)
    assert "`[COMPLETE]` handoff" in _text(HANDOFF_PARTIAL)


@pytest.mark.parametrize(
    "path",
    [p for p in FULL_PROMPTS if "cursor" not in p.parts],
    ids=lambda p: str(p.relative_to(PROJECT_ROOT)),
)
def test_argument_hint_accepts_inline_acceptance_criteria(path: Path) -> None:
    text = _text(path)

    assert "argument-hint: Specify the plan file path or acceptance criteria, and the task" in text
    assert "argument-hint: Specify the plan file path and task to implement" not in text
