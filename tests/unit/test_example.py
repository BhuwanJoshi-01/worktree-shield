"""The conflicting-worktrees example finds what its README says (WTS-011, WTS-012)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

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


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    *extra: str,
) -> tuple[int, dict[str, Any]]:
    args = ["worktree-shield", "scan", "--repo", str(repo), "--scope", "static", "--strict"]
    monkeypatch.setattr(sys, "argv", [*args, "--format", "json", *extra])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    code = exit_info.value.code
    return (code if isinstance(code, int) else 0), json.loads(capsys.readouterr().out)


def _scan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repo: Path,
    *extra: str,
) -> tuple[int, dict[str, list[str]]]:
    code, document = _run(monkeypatch, capsys, repo, *extra)
    found: dict[str, list[str]] = {}
    for finding in document["findings"]:
        found.setdefault(finding["id"], []).append(finding["status"])
    return code, found


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


@pytest.mark.xfail(strict=True, reason="WTS-009")
def test_following_the_plan_passes_strict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # The changes `worktree-shield plan` suggests for the example, made by hand: each
    # other worktree gets its own .env. The scan that reads them must then pass.
    main = _builder().build(tmp_path / "demo", fixed=False)
    for name, port in (("app-billing", 5174), ("app-login", 5175)):
        slug = name.replace("-", "_")
        (main.parent / name / ".env").write_text(
            f"PORT={port}\n"
            f"DATABASE_URL=postgres://localhost:5432/app_dev_{slug}\n"
            f"COMPOSE_PROJECT_NAME={name}\n",
            encoding="utf-8",
        )
    code, found = _scan(monkeypatch, capsys, main, "--include-env")
    assert code == 0
    assert found["WTS-PORT-001"] == ["pass"]
    assert found["WTS-DB-001"] == ["pass"]
    assert found["WTS-DOCKER-001"] == ["pass"]


@pytest.mark.xfail(strict=True, reason="WTS-009")
def test_a_fix_in_env_files_is_checked_with_include_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # The values come from .env.example and the fix goes into .env, which a plain
    # scan does not read: the check command has to say --include-env.
    main = _builder().build(tmp_path / "demo", fixed=False)
    _, document = _run(monkeypatch, capsys, main)
    port = next(f for f in document["findings"] if f["id"] == "WTS-PORT-001")
    assert port["verify_command"] == "worktree-shield scan --strict --include-env"
