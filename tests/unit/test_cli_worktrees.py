"""`worktree-shield worktrees` (WTS-001)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from rich.console import Console

from tests.gitrepos import add_worktree, git, make_repo
from worktree_shield import cli
from worktree_shield.models import (
    FailureKind,
    ProbeFailure,
    Repository,
    Snapshot,
    Worktree,
)
from worktree_shield.privacy import strip_control
from worktree_shield.reports.terminal import common_parent, display_path, render_worktrees


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["worktree-shield", *args])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    code = exit_info.value.code
    return code if isinstance(code, int) else 0


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(strip_control(capsys.readouterr().out).split())


def test_lists_the_worktrees_of_a_real_repository(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path)
    add_worktree(main, tmp_path / "login", "feature-login")
    add_worktree(main, tmp_path / "billing")
    git(main, "worktree", "lock", "--reason", "agent busy", str(tmp_path / "billing"))
    assert _run(monkeypatch, "worktrees", "--repo", str(tmp_path / "login")) == 0
    out = _out(capsys)
    assert "3 worktrees sharing" in out
    assert "* login feature-login" in out
    assert "app main" in out
    assert "billing detached at" in out
    assert "locked: agent busy" in out


def test_outside_a_repository_exits_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert _run(monkeypatch, "worktrees", "--repo", str(tmp_path)) == 3
    assert "is not inside a Git repository" in capsys.readouterr().err


def _render(snapshot: Snapshot) -> str:
    console = Console(width=200, color_system=None)
    with console.capture() as capture:
        render_worktrees(snapshot, console)
    return capture.get()


def test_failed_discovery_lists_the_reason() -> None:
    failure = ProbeFailure("git rev-parse", FailureKind.NOT_FOUND, "git was not found")
    out = _render(Snapshot(tool_version="0.1.0", created_at="x", probe_failures=(failure,)))
    assert "The worktrees could not be listed:" in out
    assert "git rev-parse: git was not found" in out


def test_bare_and_prunable_worktrees_are_explained() -> None:
    repository = Repository(
        "/srv/app.git",
        None,
        True,
        (
            Worktree("/srv/app.git", bare=True),
            Worktree("/srv/gone", "abc1234def", "refs/heads/old", prunable=""),
        ),
    )
    out = _render(Snapshot(tool_version="0.1.0", created_at="x", repository=repository))
    assert "app.git" in out
    assert "bare repository" in out
    assert "prunable" in out
    assert "never prunes them" in out
    assert "*" not in out  # no current worktree in a bare repository


def test_markup_in_branch_names_is_printed_literally() -> None:
    repository = Repository(
        "/srv/app/.git", "/srv/app", False, (Worktree("/srv/app", "a" * 40, "refs/heads/[bold]x"),)
    )
    assert "[bold]x" in _render(
        Snapshot(tool_version="0.1.0", created_at="x", repository=repository)
    )


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        ("plain", "plain"),
        ("new\nline", "new\\nline"),
        ("tab\there", "tab\\there"),
        ("bell\x07", "bell\\x07"),
    ],
)
def test_display_path_keeps_one_line(path: str, shown: str) -> None:
    assert display_path(path) == shown


@pytest.mark.parametrize(
    ("paths", "parent"),
    [
        (["/srv/a", "/srv/b"], "/srv"),
        (["/srv/app", "/srv/app/.worktrees/x"], "/srv"),
        (["/a", "/b"], None),
        (["/srv/only"], "/srv"),
    ],
)
def test_common_parent(paths: list[str], parent: str | None) -> None:
    expected = None if parent is None else os.path.normpath(parent)
    result = common_parent([os.path.normpath(p) for p in paths])
    assert (os.path.normpath(result) if result else None) == expected
