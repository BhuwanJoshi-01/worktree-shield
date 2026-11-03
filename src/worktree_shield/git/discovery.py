"""Find the repository and its worktrees, without changing anything in ``.git``.

Every git command runs as ``git -c core.fsmonitor=false -C <dir> …`` with
``GIT_OPTIONAL_LOCKS=0`` (no index refresh, so no ``index.lock``),
``GIT_TERMINAL_PROMPT=0`` (never wait for credentials) and ``LC_ALL=C``. Disabling the
fsmonitor stops a repository-configured program from being run. Only ``rev-parse``
and ``worktree list`` are used; nothing is pruned, repaired or locked.
"""

from __future__ import annotations

from pathlib import Path

from worktree_shield.git.porcelain import PorcelainError, parse_worktree_list
from worktree_shield.models import FailureKind, ProbeFailure, Repository
from worktree_shield.runner import CommandResult, CommandRunner, probe_failure

GIT_TIMEOUT = 10.0
"""Seconds; worktree listing reads a few small files."""

GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


class NotARepositoryError(Exception):
    """The directory is not inside a Git repository (exit code 3, not a failure)."""


def git_argv(directory: Path, *args: str) -> list[str]:
    return ["git", "-c", "core.fsmonitor=false", "-C", str(directory), *args]


def _git(runner: CommandRunner, directory: Path, *args: str) -> CommandResult:
    return runner.run(git_argv(directory, *args), timeout=GIT_TIMEOUT, env_overrides=GIT_ENV)


def discover(
    runner: CommandRunner, start: Path
) -> tuple[Repository | None, tuple[ProbeFailure, ...]]:
    """The repository containing ``start`` and all its worktrees.

    Raises :class:`NotARepositoryError` when ``start`` is not in a repository; any
    other problem (git missing, a repository owned by another user, a timeout) is a
    ProbeFailure and no repository.
    """
    result = _git(
        runner,
        start,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        "--is-bare-repository",
    )
    if not result.ok and "not a git repository" in result.stderr:
        raise NotARepositoryError(result.stderr.strip().splitlines()[0])
    failure = probe_failure("git rev-parse", result)
    if failure is not None:
        return None, (failure,)
    lines = result.stdout.splitlines()
    if len(lines) != 2 or lines[1] not in {"true", "false"}:
        return None, (_malformed("git rev-parse", "expected the common directory and true/false"),)
    common_dir, bare = lines[0], lines[1] == "true"

    current: str | None = None
    if not bare:
        result = _git(runner, start, "rev-parse", "--path-format=absolute", "--show-toplevel")
        failure = probe_failure("git rev-parse --show-toplevel", result)
        if failure is not None:
            return None, (failure,)
        current = result.stdout.strip() or None

    result = _git(runner, start, "worktree", "list", "--porcelain", "-z")
    failure = probe_failure("git worktree list", result)
    if failure is not None:
        return None, (failure,)
    if result.stdout_truncated:
        return None, (_malformed("git worktree list", "the list was longer than the output cap"),)
    try:
        worktrees = parse_worktree_list(result.stdout)
    except PorcelainError as exc:
        return None, (_malformed("git worktree list", str(exc)),)
    return Repository(common_dir, current, bare, worktrees), ()


def _malformed(probe: str, detail: str) -> ProbeFailure:
    return ProbeFailure(probe, FailureKind.MALFORMED_OUTPUT, detail)
