"""Suggested changes that would resolve the collisions; never applied (WTS-009)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from worktree_shield import cli
from worktree_shield.orchestrator import diagnose, inspect_resources
from worktree_shield.runner import SubprocessRunner

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-009")

BUILDER = Path(__file__).parents[2] / "examples" / "conflicting-worktrees" / "build.py"


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
    (main / "vite.config.ts").write_text("export default { server: { port: 5173 } }\n")
    return main


def _plan(main: Path) -> list[Any]:
    from worktree_shield.plan import make_plan

    snapshot = diagnose(inspect_resources(SubprocessRunner(), main, include_runtime=False))
    return [(Path(s.worktree).name, s.where, s.change, s.rule) for s in make_plan(snapshot)]


def test_the_current_worktree_keeps_its_values(example: Path) -> None:
    plan = _plan(example)
    assert all(worktree != "app" for worktree, *_ in plan)


def test_each_other_worktree_gets_its_own_values(example: Path) -> None:
    plan = _plan(example)
    assert ("app-login", ".env", "PORT=5174", "WTS-PORT-001") in plan
    assert ("app-billing", ".env", "PORT=5175", "WTS-PORT-001") in plan
    assert (
        "app-login",
        ".env",
        "DATABASE_URL naming the database app_dev_app_login instead of app_dev",
        "WTS-DB-001",
    ) in plan
    assert ("app-login", ".env", "COMPOSE_PROJECT_NAME=app-login", "WTS-DOCKER-001") in plan


def test_files_other_than_env_templates_are_changed_in_place(example: Path) -> None:
    plan = _plan(example)
    assert (
        "app-login",
        "vite.config.ts:1",
        "server.port: 5173 → 5174",
        "WTS-PORT-001",
    ) in plan


def test_a_volume_that_follows_from_the_project_needs_no_change_of_its_own(example: Path) -> None:
    assert not [entry for entry in _plan(example) if entry[3] == "WTS-DOCKER-003"]


def test_new_ports_avoid_every_port_already_claimed(example: Path) -> None:
    (example / ".env.example").write_text(
        "PORT=5173\nAPI_PORT=5174\nDATABASE_URL=postgres://a:b@localhost/app_dev\n"
    )
    ports = [change for _, where, change, rule in _plan(example) if change.startswith("PORT=")]
    assert ports == ["PORT=5175", "PORT=5176"]


def test_the_plan_command_writes_nothing(
    example: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.gitrepos import tree_digest

    before = tree_digest(example.parent)
    monkeypatch.setattr(
        sys, "argv", ["worktree-shield", "plan", "--repo", str(example), "--scope", "static"]
    )
    monkeypatch.setenv("COLUMNS", "300")
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code in (0, None)
    out = capsys.readouterr().out
    assert "Nothing was changed" in out
    assert "app-login" in out
    assert "PORT=5174" in out
    assert tree_digest(example.parent) == before


def test_nothing_to_suggest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.gitrepos import make_repo

    main = make_repo(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["worktree-shield", "plan", "--repo", str(main), "--scope", "static"]
    )
    with pytest.raises(SystemExit):
        cli.main()
    assert "Nothing to change" in capsys.readouterr().out
