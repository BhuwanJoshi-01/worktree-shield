import pytest

from tests.fakes import FakeRunner, UnexpectedCommandError
from worktree_shield.runner import CommandResult, CommandRunner, Outcome


def test_fake_runner_answers_scripted_commands_and_records_calls() -> None:
    fake = FakeRunner()
    fake.script("git", "rev-parse", "--git-common-dir", stdout=".git\n")
    runner: CommandRunner = fake
    result = runner.run(
        ["git", "rev-parse", "--git-common-dir"], timeout=8, env_overrides={"LC_ALL": "C"}
    )
    assert result.ok
    assert result.stdout == ".git\n"
    assert fake.calls[0].argv == ("git", "rev-parse", "--git-common-dir")
    assert fake.calls[0].env_overrides == {"LC_ALL": "C"}


def test_fake_runner_fails_the_test_on_unscripted_commands() -> None:
    with pytest.raises(UnexpectedCommandError, match="rm"):
        FakeRunner().run(["rm", "-rf", "build"], timeout=1)


def test_fake_runner_can_return_any_outcome() -> None:
    fake = FakeRunner()
    fake.script_result(CommandResult(("git",), Outcome.TIMEOUT, duration=5))
    assert fake.run(["git"], timeout=5).outcome is Outcome.TIMEOUT
