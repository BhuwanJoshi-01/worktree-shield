"""Runs the collectors and assembles the snapshot; no diagnosis happens here."""

from __future__ import annotations

from pathlib import Path

from worktree_shield import __version__
from worktree_shield.git.discovery import discover
from worktree_shield.models import Snapshot, utc_timestamp
from worktree_shield.runner import CommandRunner


def inspect_worktrees(runner: CommandRunner, start: Path) -> Snapshot:
    """The repository containing ``start`` and its worktrees.

    Raises ``NotARepositoryError`` when ``start`` is not inside a repository.
    """
    repository, failures = discover(runner, start)
    return Snapshot(
        tool_version=__version__,
        created_at=utc_timestamp(),
        repository=repository,
        probe_failures=failures,
    )
