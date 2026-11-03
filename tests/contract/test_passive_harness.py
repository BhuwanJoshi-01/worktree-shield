"""A whole scan runs only read-only git, and nothing else (WTS-010).

``is_read_only()`` is THE definition of what worktree-shield may run. Every command of
a full scan of the example repository is recorded and checked against it, and the
process-starting functions of the standard library are watched, so a collector that
starts a program behind the runner's back fails here too.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from worktree_shield.orchestrator import diagnose, inspect_resources
from worktree_shield.runner import CommandResult, SubprocessRunner

BUILDER = Path(__file__).parents[2] / "examples" / "conflicting-worktrees" / "build.py"
_PREFIX = ["git", "-c", "core.fsmonitor=false", "-C"]
_REV_PARSE = {
    "--path-format=absolute",
    "--git-common-dir",
    "--is-bare-repository",
    "--show-toplevel",
}
_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


def is_read_only(argv: Sequence[str], env: Mapping[str, str] | None) -> bool:
    """git with fsmonitor off, optional locks off, no prompt, and one of the two reads."""
    if list(argv[:4]) != _PREFIX or len(argv) < 6:
        return False
    if any((env or {}).get(name) != value for name, value in _ENV.items()):
        return False
    command = list(argv[5:])
    if command[0] == "rev-parse":
        return set(command[1:]) <= _REV_PARSE
    return command == ["worktree", "list", "--porcelain", "-z"]


@pytest.mark.parametrize(
    "argv",
    [
        [*_PREFIX, "/r", "worktree", "prune"],
        [*_PREFIX, "/r", "worktree", "add", "/x"],
        [*_PREFIX, "/r", "worktree", "list"],  # the porcelain form only
        [*_PREFIX, "/r", "gc"],
        [*_PREFIX, "/r", "rev-parse", "--git-path", "x"],
        [*_PREFIX, "/r", "status"],  # refreshes the index
        ["git", "-C", "/r", "rev-parse", "--git-common-dir"],  # fsmonitor not off
        ["docker", "compose", "ls"],
        ["sh", "-c", "git worktree list"],
    ],
)
def test_the_harness_rejects_anything_else(argv: list[str]) -> None:
    assert not is_read_only(argv, _ENV)


def test_the_harness_needs_the_safe_environment() -> None:
    argv = [*_PREFIX, "/r", "worktree", "list", "--porcelain", "-z"]
    assert is_read_only(argv, _ENV)
    assert not is_read_only(argv, {"GIT_TERMINAL_PROMPT": "0"})


class Recording:
    """The real runner, recording every command."""

    def __init__(self) -> None:
        self.inner = SubprocessRunner()
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        env_overrides: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        self.calls.append((list(argv), dict(env_overrides or {})))
        return self.inner.run(argv, timeout=timeout, env_overrides=env_overrides, cwd=cwd)


@pytest.fixture
def example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    spec = importlib.util.spec_from_file_location("example_build", BUILDER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    main: Path = module.build(tmp_path / "demo", fixed=False)
    for worktree in (main, tmp_path / "demo" / "app-login"):
        (worktree / ".env").write_text("PORT=1\n", encoding="utf-8")
    return main


def test_a_full_scan_runs_only_read_only_git(
    example: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[Any] = []
    real_popen = subprocess.Popen

    class Watched(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
            started.append(args)
            super().__init__(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Watched)
    for name in ("system", "popen", "execv", "execvp", "spawnv", "posix_spawn"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, lambda *a, _n=name, **k: pytest.fail(f"os.{_n} called"))
    runner = Recording()
    snapshot = diagnose(inspect_resources(runner, example, include_env_files=True))
    assert snapshot.findings
    assert runner.calls
    for argv, env in runner.calls:
        assert is_read_only(argv, env), argv
    assert len(started) == len(runner.calls)  # nothing started behind the runner's back
