"""Tests for the symbolic verification command path in `harness/fusion/verifier.py`.

These cover the plan step 10 contract:

* Configured ``success_commands`` produce ``VerifierResult.checks`` entries with
  command name, pass/fail status, and command output path.
* The check name for a command check is the literal
  ``symbolic_verification_command`` (canonical across pass and fail).
* A failing command sets ``VerifierResult.pass_`` to ``False`` and emits a
  failed check named ``symbolic_verification_command``.
* Command output is persisted under ``verifier/commands/`` for both pass and
  fail cases.
* The model-verifier cannot rescue a failed symbolic command — a run with a
  failing ``success_command`` stays failed even when the independent verifier
  would otherwise accept the answer.
"""

from __future__ import annotations

from pathlib import Path

from harness.core.task_contract import load_task_contract
from harness.fusion.synthesizer import SynthesisResult
from harness.fusion.verifier import Verifier


def _task() -> "object":  # TaskContract
    return load_task_contract(
        Path("tests/fixtures/task_with_commands.json"), Path.cwd()
    )


def _synthesis() -> SynthesisResult:
    return SynthesisResult(
        synthesis_id="s1",
        run_id="r1",
        status="completed",
        final_answer="a non-empty answer",
        used_candidate_parts=[{"candidate_id": "c1", "component": "answer"}],
        trace_path="t",
    )


def test_fixture_task_has_one_passing_and_one_failing_command() -> None:
    """The fixture must match the plan: one pass, one fail."""
    task = _task()
    assert task.success_commands == [
        "python -m pytest --version",
        "python -m pytest definitely_missing_test_file_for_verifier_check.py",
    ]


def test_command_check_uses_canonical_name(tmp_path: Path) -> None:
    res = Verifier().verify(_task(), _synthesis(), tmp_path, tmp_path)
    command_checks = [c for c in res.checks if c.type == "command"]
    assert command_checks, "expected at least one command check"
    for check in command_checks:
        assert check.name == "symbolic_verification_command"
        assert check.command is not None
        assert check.output_path is not None


def test_passing_command_produces_passed_check_with_output_path(tmp_path: Path) -> None:
    res = Verifier().verify(_task(), _synthesis(), tmp_path, tmp_path)
    passed = [c for c in res.checks if c.name == "symbolic_verification_command" and c.status == "passed"]
    assert len(passed) == 1, f"expected exactly one passing command check, got {passed}"
    # Output path lives under verifier/commands/ (cross-platform: check path parts).
    assert passed[0].output_path is not None
    assert Path(passed[0].output_path).parts[-3:-1] == ("verifier", "commands")
    assert Path(passed[0].output_path).exists()


def test_failing_command_sets_pass_to_false_with_symbolic_check_name(tmp_path: Path) -> None:
    res = Verifier().verify(_task(), _synthesis(), tmp_path, tmp_path)
    failed = [c for c in res.checks if c.name == "symbolic_verification_command" and c.status == "failed"]
    assert len(failed) == 1, f"expected exactly one failed command check, got {failed}"
    # A failed command check forces the overall verifier result to fail.
    assert res.pass_ is False
    # Repair instructions are populated.
    assert any("success_commands" in r or "command" in r for r in res.required_repairs)


def test_command_output_files_written_under_verifier_commands(tmp_path: Path) -> None:
    Verifier().verify(_task(), _synthesis(), tmp_path, tmp_path)
    commands_dir = tmp_path / "verifier" / "commands"
    assert commands_dir.exists()
    logs = sorted(commands_dir.glob("command_*.stdout.log"))
    assert len(logs) == 2
    # Both stdout and stderr are written.
    for stdout_log in logs:
        stderr_log = stdout_log.with_name(stdout_log.name.replace("stdout", "stderr"))
        assert stdout_log.exists()
        assert stderr_log.exists()


def test_disallowed_command_produces_failed_check(tmp_path: Path) -> None:
    """A command not on the allowlist fails the symbolic gate without being run."""
    task = _task()
    task.success_commands = ["git reset --hard"]  # on the deny list
    res = Verifier().verify(task, _synthesis(), tmp_path, tmp_path)
    assert res.pass_ is False
    failed = [c for c in res.checks if c.name == "symbolic_verification_command" and c.status == "failed"]
    assert len(failed) == 1
    assert "blocked dangerous command" in (failed[0].summary or "")


def test_all_commands_passing_keeps_pass_true(tmp_path: Path) -> None:
    """Regression: when every configured command passes, the verifier still passes."""
    task = _task()
    task.success_commands = ["python -m pytest --version"]
    res = Verifier().verify(task, _synthesis(), tmp_path, tmp_path)
    assert res.pass_ is True
    passed = [c for c in res.checks if c.name == "symbolic_verification_command" and c.status == "passed"]
    assert len(passed) == 1
