"""Listen ports in pyproject.toml task runners (WTS-003)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from tests.fakes import read_fixture
from worktree_shield.models import Policy

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-003")


def _collect(root: Path) -> Any:
    from worktree_shield.collectors.base import Collected, Scope
    from worktree_shield.collectors.python import collect_pyproject

    out = Collected()
    collect_pyproject(Scope(root, "/repos/api", Policy().max_file_bytes), PurePosixPath(), out)
    return out


def test_every_task_runner(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(read_fixture("python", "pyproject.toml"))
    claims = [(c.key, c.source.line, c.detail, c.strict) for c in _collect(tmp_path).claims]
    assert claims == [
        ("tcp://*:8000", 7, "tool.poe.tasks.serve: --port 8000", None),
        ("tcp://*:8002", 11, "tool.poe.tasks.worker: env.PORT=8002", None),
        ("tcp://*:8003", 16, "tool.taskipy.tasks.dev: runserver 8003", None),
        ("tcp://0.0.0.0:8004", 19, "tool.pdm.scripts.start: -b 0.0.0.0:8004", None),
        ("tcp://*:8005", 20, "tool.pdm.scripts.shell-task: PORT=8005", None),
        ("tcp://*:8006", 21, "tool.pdm.scripts.all: http.server 8006", None),
        ("tcp://*:5173", 24, "tool.hatch.envs.default.scripts.web: --port 5173", True),
        ("tcp://*:8007", 27, "tool.rye.scripts.api:dev: --port 8007", None),
    ]


@pytest.mark.parametrize(
    "text",
    [
        '[project]\nname = "x"\n',
        '[tool.poe]\ntasks = "uvicorn --port 1"\n',
        '[tool.poe.tasks]\nrun = { script = "api:main(port=8000)" }\n',
        "[tool.pdm.scripts]\nx = 8000\n",
        '[tool.hatch.envs]\ndefault = "x"\n',
        "[tool.rye]\nscripts = []\n",
    ],
)
def test_other_shapes_yield_nothing(tmp_path: Path, text: str) -> None:
    (tmp_path / "pyproject.toml").write_text(text)
    out = _collect(tmp_path)
    assert out.claims == []
    assert out.skipped == []


def test_invalid_toml_is_reported_as_skipped(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.poe.tasks\nserve = 1\n")
    (skipped,) = _collect(tmp_path).skipped
    assert (skipped.source.path, skipped.reason) == ("pyproject.toml", "is not valid TOML")


def test_deeply_nested_sequences_are_cut_off(tmp_path: Path) -> None:
    nested = "x"
    for _ in range(30):
        nested = f"{{ sequence = [{nested}] }}" if nested != "x" else '"vite --port 1"'
    (tmp_path / "pyproject.toml").write_text(f"[tool.poe.tasks]\ndeep = {nested}\n")
    assert _collect(tmp_path).claims == []  # beyond the depth limit, not a crash
