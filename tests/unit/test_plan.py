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
    vite = main.parent / "app-login" / "vite.config.ts"
    vite.write_text("export default { server: { port: 5173 } }\n", encoding="utf-8")
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
    # the worktrees that change are taken in path order: app-billing, then app-login
    assert ("app-billing", ".env", "PORT=5174", "WTS-PORT-001") in plan
    assert ("app-login", ".env", "PORT=5175", "WTS-PORT-001") in plan
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
        "server.port: 5173 → server.port: 5175",
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


COMPOSE = "name: app\nservices:\n  db:\n    image: postgres\n    ports: ['5432:5432']\n"
ENV = "PORT=5173\nREDIS_URL=redis://localhost:6379/0\nUPLOAD_DIR=/srv/uploads\n"


def test_compose_redis_paths_and_one_port_per_worktree(example: Path) -> None:
    login = example.parent / "app-login"
    for worktree in (example, login):
        (worktree / "compose.yaml").write_text(COMPOSE, encoding="utf-8")
        (worktree / ".env.example").write_text(ENV, encoding="utf-8")
    plan = [entry for entry in _plan(example) if entry[0] == "app-login"]
    host_port_only = "services.db.ports: 5432:5432 → services.db.ports: 5433:5432"
    assert ("app-login", "compose.yaml:5", host_port_only, "WTS-PORT-001") in plan
    redis = "REDIS_URL naming the database 1 instead of 0"  # app-billing has no Redis
    assert ("app-login", ".env", redis, "WTS-DB-001") in plan
    assert ("app-login", ".env", "UPLOAD_DIR=/srv/uploads-app-login", "WTS-PATH-001") in plan
    ports = [c for _, where, c, _ in plan if where == ".env" and c.startswith("PORT=")]
    assert len(ports) == 1  # one port per worktree and old port, however many findings


def _synthetic(*findings: Any, runtime: Any = None) -> list[Any]:
    from worktree_shield.models import Policy, Repository, Snapshot, Worktree
    from worktree_shield.plan import make_plan

    repository = Repository("/r/.git", "/r/app", False, (Worktree("/r/app"), Worktree("/r/b")))
    snapshot = Snapshot(
        "0", "t", repository=repository, policy=Policy(), findings=findings, runtime=runtime
    )
    return [(s.worktree, s.where, s.change, s.rule) for s in make_plan(snapshot)]


def _f(rule: str, key: str, evidence: tuple[Any, ...], summary: str = "s", **extra: Any) -> Any:
    from worktree_shield.models import Confidence, Finding, Severity, Status

    worktrees = tuple(dict.fromkeys(e.key for e in evidence))
    return Finding(
        rule,
        Status.WARN,
        Severity.LOW,
        Confidence.LOW,
        summary,
        "r",
        resource_key=key,
        worktrees=worktrees,
        evidence=evidence,
        **extra,
    )


def test_a_port_held_outside_moves_every_worktree_and_avoids_busy_ports() -> None:
    from worktree_shield.models import Evidence, Listener, RuntimeFacts

    busy = RuntimeFacts(
        (Listener("tcp", "0.0.0.0", 5433, None, None, "owned by a process of another user"),)
    )
    held = _f(
        "WTS-PORT-002",
        "tcp://0.0.0.0:5432",
        (
            Evidence("compose.yaml:5", "/r/app", "services.db.ports: 5432:5432"),
            Evidence("pid 9", "/r/b", "x"),
        ),
        summary="Port 5432 is already in use",
    )
    plan = _synthetic(held, runtime=busy)
    assert plan == [
        (
            "/r/app",
            "compose.yaml:5",
            "services.db.ports: 5432:5432 → services.db.ports: 5434:5432",
            "WTS-PORT-002",
        )
    ]


def test_containers_volumes_and_findings_without_a_plan() -> None:
    from worktree_shield.models import Evidence

    container = _f(
        "WTS-DOCKER-002",
        "container://db",
        (Evidence("compose.yaml:4", "/r/app", "c"), Evidence("compose.yaml:4", "/r/b", "c")),
    )
    volume = _f(
        "WTS-DOCKER-003",
        "volume://data",
        (Evidence("compose.yaml:7", "/r/app", "v"), Evidence("compose.yaml:7", "/r/b", "v")),
    )
    followed = _f(
        "WTS-DOCKER-003",
        "volume://app_data",
        (Evidence("x", "/r/b", "v"),),
        caused_by="WTS-DOCKER-001",
    )
    unplanned = _f("WTS-ENV-001", "x://y", (Evidence(".env", "/r/b", "not read"),))
    plan = _synthetic(container, volume, followed, unplanned)
    assert plan == [
        (
            "/r/b",
            "compose.yaml:4",
            "container_name: remove it, or use ${COMPOSE_PROJECT_NAME}-db",
            "WTS-DOCKER-002",
        ),
        ("/r/b", "compose.yaml:7", "data → data-b", "WTS-DOCKER-003"),
    ]


def test_a_value_without_the_old_port_and_no_repository() -> None:
    from worktree_shield.models import Evidence, Snapshot
    from worktree_shield.plan import make_plan

    odd = _f(
        "WTS-PORT-001",
        "tcp://*:80",
        (Evidence("Procfile:1", "/r/app", "x"), Evidence("Procfile:1", "/r/b", "web")),
    )
    assert _synthetic(odd) == [("/r/b", "Procfile:1", "web → port 81", "WTS-PORT-001")]
    assert make_plan(Snapshot("0", "t")) == []


@pytest.mark.xfail(strict=True, reason="WTS-009")
def test_the_plan_names_the_scan_that_reads_its_env_changes(
    example: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["worktree-shield", "plan", "--repo", str(example), "--scope", "static"]
    )
    monkeypatch.setenv("COLUMNS", "300")
    with pytest.raises(SystemExit):
        cli.main()
    out = " ".join(capsys.readouterr().out.split())
    assert "then run worktree-shield scan --strict --include-env" in out
