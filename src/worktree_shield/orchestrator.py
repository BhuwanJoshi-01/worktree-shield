"""Runs the collectors and assembles the snapshot; no diagnosis happens here."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from worktree_shield import __version__
from worktree_shield.collectors.base import Collected, Scope
from worktree_shield.collectors.static import collect_worktree
from worktree_shield.config import apply_overrides, policy_of
from worktree_shield.git.discovery import discover
from worktree_shield.models import SkippedFile, Snapshot, SourceRef, utc_timestamp
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


def inspect_resources(
    runner: CommandRunner, start: Path, *, include_env_files: bool | None = None
) -> Snapshot:
    """The worktrees of the repository, the effective policy and every resource the
    worktrees declare in their configuration.

    Bare and prunable worktrees have no files to read and are left out. Raises
    ``NotARepositoryError`` outside a repository and ``PolicyError`` for a policy file
    that cannot be used.
    """
    snapshot = inspect_worktrees(runner, start)
    if snapshot.repository is None:
        return snapshot
    policy = apply_overrides(policy_of(snapshot.repository), include_env_files=include_env_files)
    out = Collected()
    for worktree in snapshot.repository.worktrees:
        if worktree.bare or worktree.prunable is not None:
            continue
        root = Path(worktree.path)
        if not root.is_dir():
            reason = "is listed by Git but is not a directory"
            out.skipped.append(SkippedFile(SourceRef(worktree.path, "."), reason))
            continue
        collect_worktree(Scope(root, worktree.path, policy.max_file_bytes), policy, out)
    return replace(
        snapshot,
        policy=policy,
        claims=tuple(out.claims),
        skipped=tuple(out.skipped),
        unreadable=tuple(out.unreadable),
    )
