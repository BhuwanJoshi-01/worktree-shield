"""The conflicting-worktrees example finds what its README says (WTS-011, WTS-012)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from worktree_shield import cli

BUILDER = Path(__file__).parents[2] / "examples" / "conflicting-worktrees" / "build.py"


@pytest.fixture(autouse=True)
def no_global_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """The builder uses git as the user has it; tests must not depend on that."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("example_build", BUILDER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], repo: Path
) -> tuple[int, dict[str, list[str]]]:
    args = [
        "worktree-shield",
        "scan",
        "--repo",
        str(repo),
        "--scope",
        "static",
        "--strict",
        "--format",
        "json",
    ]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    document = json.loads(capsys.readouterr().out)
    found: dict[str, list[str]] = {}
    for finding in document["findings"]:
        found.setdefault(finding["id"], []).append(finding["status"])
    code = exit_info.value.code
    return (code if isinstance(code, int) else 0), found


def test_the_collisions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = _builder().build(tmp_path / "demo", fixed=False)
    code, found = _scan(monkeypatch, capsys, main)
    assert code == 1
    assert found["WTS-PORT-001"] == ["fail"]
    assert found["WTS-DB-001"] == ["warn"]
    assert found["WTS-DOCKER-001"] == ["warn"]
    assert found["WTS-DOCKER-003"] == ["warn"]


def test_the_fixed_version_passes_strict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = _builder().build(tmp_path / "fixed", fixed=True)
    code, found = _scan(monkeypatch, capsys, main)
    assert code == 0
    assert found["WTS-PORT-001"] == ["pass"]
    assert found["WTS-DB-001"] == ["pass"]
    assert found["WTS-DOCKER-001"] == ["pass"]


def test_the_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    builder = _builder()
    assert builder.main([]) == 2
    assert builder.main([str(tmp_path / "demo")]) == 0
    assert "Built" in capsys.readouterr().out
    assert builder.main([str(tmp_path / "demo")]) == 2  # never overwrites
