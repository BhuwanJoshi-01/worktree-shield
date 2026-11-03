"""The installed command and ``python -m`` start the same CLI."""

from __future__ import annotations

import sys
import sysconfig
from pathlib import Path

import pytest

from worktree_shield import __version__
from worktree_shield.runner import Outcome, SubprocessRunner


def _console_script(name: str = "worktree-shield") -> Path:
    if sys.platform == "win32":
        name += ".exe"
    return Path(sysconfig.get_path("scripts")) / name


@pytest.mark.parametrize(
    "argv",
    [
        [sys.executable, "-m", "worktree_shield", "--version"],
        [str(_console_script()), "--version"],
        [str(_console_script("wtshield")), "--version"],
    ],
    ids=["python -m", "console script", "wtshield alias"],
)
def test_entry_point_prints_the_version(argv: list[str]) -> None:
    result = SubprocessRunner().run(argv, timeout=30)
    assert result.outcome is Outcome.OK, result.stderr
    assert result.stdout.strip() == f"worktree-shield {__version__}"
