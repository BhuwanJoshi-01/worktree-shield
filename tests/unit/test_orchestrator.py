from __future__ import annotations

from pathlib import Path

import pytest

from tests.gitrepos import add_worktree, make_repo
from worktree_shield import __version__
from worktree_shield.git.discovery import NotARepositoryError
from worktree_shield.orchestrator import inspect_worktrees
from worktree_shield.runner import SubprocessRunner


def test_inspect_worktrees_builds_a_snapshot(tmp_path: Path) -> None:
    main = make_repo(tmp_path)
    add_worktree(main, tmp_path / "second", "second")
    snapshot = inspect_worktrees(SubprocessRunner(), main)
    assert snapshot.tool_version == __version__
    assert snapshot.probe_failures == ()
    assert snapshot.repository is not None
    assert len(snapshot.repository.worktrees) == 2


def test_inspect_worktrees_outside_a_repository(tmp_path: Path) -> None:
    with pytest.raises(NotARepositoryError):
        inspect_worktrees(SubprocessRunner(), tmp_path)
