"""Finding the repository and its worktrees with real git (WTS-001)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.fakes import FakeRunner
from tests.gitrepos import add_worktree, git, make_repo, same_path, tree_digest
from worktree_shield.git.discovery import GIT_ENV, NotARepositoryError, discover, git_argv
from worktree_shield.models import FailureKind
from worktree_shield.runner import CommandResult, Outcome, SubprocessRunner


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    main = make_repo(tmp_path)
    add_worktree(main, tmp_path / "with space", "feature-a")
    add_worktree(main, tmp_path / "ünïcode", "feature-b")
    add_worktree(main, tmp_path / "detached")
    return main


def test_discovery_from_the_main_worktree(repo: Path) -> None:
    found, failures = discover(SubprocessRunner(), repo)
    assert failures == ()
    assert found is not None
    assert not found.bare
    assert same_path(found.current, repo)
    assert same_path(found.common_dir, repo / ".git")
    assert len(found.worktrees) == 4
    assert same_path(found.worktrees[0].path, repo)  # Git lists the main worktree first
    names = sorted(Path(w.path).name for w in found.worktrees[1:])
    assert names == sorted(["with space", "ünïcode", "detached"])
    detached = next(w for w in found.worktrees if Path(w.path).name == "detached")
    assert detached.detached
    assert detached.branch is None


def test_every_worktree_sees_the_same_repository(repo: Path, tmp_path: Path) -> None:
    from_main, _ = discover(SubprocessRunner(), repo)
    from_linked, _ = discover(SubprocessRunner(), tmp_path / "with space")
    assert from_main is not None
    assert from_linked is not None
    assert same_path(from_linked.common_dir, from_main.common_dir)
    assert same_path(from_linked.current, tmp_path / "with space")
    assert [w.path for w in from_linked.worktrees] == [w.path for w in from_main.worktrees]


def test_discovery_from_a_subdirectory(repo: Path) -> None:
    (repo / "src" / "deep").mkdir(parents=True)
    found, _ = discover(SubprocessRunner(), repo / "src" / "deep")
    assert found is not None
    assert same_path(found.current, repo)


def test_locked_and_prunable_worktrees_are_reported_not_touched(repo: Path, tmp_path: Path) -> None:
    git(repo, "worktree", "lock", "--reason", "on a USB disk", str(tmp_path / "detached"))
    gone = add_worktree(repo, tmp_path / "gone", "feature-gone")
    for path in sorted(gone.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    gone.rmdir()
    found, _ = discover(SubprocessRunner(), repo)
    assert found is not None
    by_name = {Path(w.path).name: w for w in found.worktrees}
    assert by_name["detached"].locked == "on a USB disk"
    assert by_name["gone"].prunable is not None
    assert "gone" in git(repo, "worktree", "list")  # still registered: nothing was pruned


@pytest.mark.skipif(sys.platform == "win32", reason="Windows paths cannot contain a newline")
def test_a_newline_in_a_worktree_path(repo: Path, tmp_path: Path) -> None:
    add_worktree(repo, tmp_path / "new\nline", "feature-c")
    found, _ = discover(SubprocessRunner(), repo)
    assert found is not None
    assert any(Path(w.path).name == "new\nline" for w in found.worktrees)


def test_bare_repository(tmp_path: Path) -> None:
    main = make_repo(tmp_path)
    git(tmp_path, "clone", "-q", "--bare", str(main), str(tmp_path / "bare.git"))
    linked = add_worktree(tmp_path / "bare.git", tmp_path / "from-bare", "feature")
    found, failures = discover(SubprocessRunner(), tmp_path / "bare.git")
    assert failures == ()
    assert found is not None
    assert found.bare
    assert found.current is None
    assert found.worktrees[0].bare
    assert same_path(found.worktrees[1].path, linked)


def test_outside_a_repository(tmp_path: Path) -> None:
    lonely = tmp_path / "not-a-repo"
    lonely.mkdir()
    with pytest.raises(NotARepositoryError):
        discover(SubprocessRunner(), lonely)


def test_a_scan_writes_nothing_into_git(repo: Path) -> None:
    (repo / "README.md").write_text("changed, so an index refresh would have work to do\n")
    before = tree_digest(repo / ".git")
    for _ in range(3):
        discover(SubprocessRunner(), repo)
    assert tree_digest(repo / ".git") == before


def test_git_runs_with_the_safe_environment() -> None:
    runner = FakeRunner()
    start = Path("/srv/app")
    runner.script(
        *git_argv(
            start, "rev-parse", "--path-format=absolute", "--git-common-dir", "--is-bare-repository"
        ),
        stdout="/srv/app/.git\nfalse\n",
    )
    runner.script(
        *git_argv(start, "rev-parse", "--path-format=absolute", "--show-toplevel"),
        stdout="/srv/app\n",
    )
    runner.script(
        *git_argv(start, "worktree", "list", "--porcelain", "-z"),
        stdout="worktree /srv/app\0HEAD abc\0branch refs/heads/main\0\0",
    )
    found, failures = discover(runner, start)
    assert failures == ()
    assert found is not None
    for call in runner.calls:
        assert call.argv[:3] == ("git", "-c", "core.fsmonitor=false")
        assert call.env_overrides == GIT_ENV
    assert GIT_ENV["GIT_OPTIONAL_LOCKS"] == "0"
    assert GIT_ENV["GIT_TERMINAL_PROMPT"] == "0"


def test_missing_git_is_a_probe_failure() -> None:
    runner = FakeRunner()
    argv = git_argv(
        Path("/srv"),
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        "--is-bare-repository",
    )
    runner.script_result(CommandResult(tuple(argv), Outcome.NOT_FOUND, error="No such file"))
    found, failures = discover(runner, Path("/srv"))
    assert found is None
    assert failures[0].kind is FailureKind.NOT_FOUND


def test_a_repository_of_another_user_is_reported() -> None:
    runner = FakeRunner()
    argv = git_argv(
        Path("/srv"),
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        "--is-bare-repository",
    )
    runner.script(
        *argv, stderr="fatal: detected dubious ownership in repository at '/srv'\n", returncode=128
    )
    found, failures = discover(runner, Path("/srv"))
    assert found is None
    assert "dubious ownership" in failures[0].detail


def test_malformed_answers_are_reported() -> None:
    runner = FakeRunner()
    start = Path("/srv/app")
    runner.script(
        *git_argv(
            start, "rev-parse", "--path-format=absolute", "--git-common-dir", "--is-bare-repository"
        ),
        stdout="/srv/app/.git\nfalse\n",
    )
    runner.script(
        *git_argv(start, "rev-parse", "--path-format=absolute", "--show-toplevel"),
        stdout="/srv/app\n",
    )
    runner.script(*git_argv(start, "worktree", "list", "--porcelain", "-z"), stdout="garbage\0\0")
    found, failures = discover(runner, start)
    assert found is None
    assert failures[0].kind is FailureKind.MALFORMED_OUTPUT
