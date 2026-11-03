"""Runs the collectors and assembles the snapshot; no diagnosis happens here."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import psutil

from worktree_shield import __version__
from worktree_shield.collectors.base import Collected, Scope
from worktree_shield.collectors.runtime import ProcessTable, PsutilTable, observe_runtime
from worktree_shield.collectors.static import collect_worktree
from worktree_shield.config import apply_overrides, policy_of
from worktree_shield.git.discovery import discover
from worktree_shield.models import (
    ResourceClaim,
    ResourceKind,
    RuntimeFacts,
    SkippedFile,
    Snapshot,
    SourceRef,
    utc_timestamp,
)
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


_PORT = re.compile(r"([a-z]+)://.*:([0-9]+)")


def inspect_resources(
    runner: CommandRunner,
    start: Path,
    *,
    include_env_files: bool | None = None,
    include_runtime: bool | None = None,
    table: ProcessTable | None = None,
) -> Snapshot:
    """The worktrees of the repository, the effective policy and every resource the
    worktrees declare in their configuration or, with ``include_runtime``, hold with a
    running server.

    Bare and prunable worktrees have no files to read and are left out. Raises
    ``NotARepositoryError`` outside a repository and ``PolicyError`` for a policy file
    that cannot be used.
    """
    snapshot = inspect_worktrees(runner, start)
    if snapshot.repository is None:
        return snapshot
    policy = apply_overrides(
        policy_of(snapshot.repository),
        include_env_files=include_env_files,
        include_runtime=include_runtime,
    )
    out = Collected()
    with_files: list[str] = []
    for worktree in snapshot.repository.worktrees:
        if worktree.bare or worktree.prunable is not None:
            continue
        root = Path(worktree.path)
        if not root.is_dir():
            reason = "is listed by Git but is not a directory"
            out.skipped.append(SkippedFile(SourceRef(worktree.path, "."), reason))
            continue
        with_files.append(worktree.path)
        collect_worktree(Scope(root, worktree.path, policy.max_file_bytes), policy, out)
    runtime = None
    if policy.include_runtime:
        runtime = _observe(table or PsutilTable(), with_files, out.claims)
    return replace(
        snapshot,
        policy=policy,
        claims=tuple(out.claims),
        skipped=tuple(out.skipped),
        unreadable=tuple(out.unreadable),
        runtime=runtime,
    )


def _observe(
    table: ProcessTable, worktrees: list[str], claims: list[ResourceClaim]
) -> RuntimeFacts:
    """Add the runtime claims to ``claims``; keep the unattributed listeners only on
    ports some worktree configures, since only those can block one."""
    try:
        found, unattributed, limitations = observe_runtime(table, worktrees)
    except (psutil.Error, OSError) as error:
        return RuntimeFacts(limitations=(f"running processes could not be listed ({error})",))
    configured = set()
    for claim in claims:
        match = _PORT.fullmatch(claim.key)
        if claim.kind is ResourceKind.LISTEN_PORT and match is not None:
            configured.add((match.group(1), int(match.group(2))))
    claims += found
    relevant = tuple(u for u in unattributed if (u.protocol, u.port) in configured)
    return RuntimeFacts(relevant, tuple(limitations))
