"""`worktree-shield resources` on real repositories (WTS-003, WTS-004, WTS-006, WTS-012)."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.gitrepos import add_worktree, git, make_repo, tree_digest
from worktree_shield import cli
from worktree_shield.config import POLICY_FILE
from worktree_shield.models import (
    FailureKind,
    ProbeFailure,
    RedactionCount,
    Repository,
    ResourceClaim,
    ResourceKind,
    Snapshot,
    SourceRef,
    Worktree,
)
from worktree_shield.orchestrator import inspect_resources
from worktree_shield.privacy import strip_control
from worktree_shield.runner import SubprocessRunner

CANARY = "Canary-Pw-77"


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["worktree-shield", *args])
    monkeypatch.setenv("COLUMNS", "300")
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    code = exit_info.value.code
    return code if isinstance(code, int) else 0


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(strip_control(capsys.readouterr().out).split())


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    """A main worktree, a sibling and one nested inside the main worktree."""
    main = make_repo(tmp_path, "shop")
    (main / "apps" / "web").mkdir(parents=True)
    (main / ".env.example").write_text(
        "PORT=5173\nDATABASE_URL=postgres://shop:x@localhost:5432/shop_dev\n", encoding="utf-8"
    )
    (main / "apps" / "web" / "vite.config.ts").write_text(
        "export default { server: { port: 5173 } }\n", encoding="utf-8"
    )
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "config")
    add_worktree(main, tmp_path / "shop-login", "login")
    nested = add_worktree(main, main / "worktrees" / "billing", "billing")
    (nested / ".env.example").write_text("PORT=5174\n", encoding="utf-8")
    return main


def test_claims_of_every_worktree(shop: Path) -> None:
    snapshot = inspect_resources(SubprocessRunner(), shop)
    claims = {(Path(c.worktree).name, c.kind, c.key, c.source.path) for c in snapshot.claims}
    assert claims == {
        ("shop", ResourceKind.LISTEN_PORT, "tcp://*:5173", ".env.example"),
        ("shop", ResourceKind.LISTEN_PORT, "tcp://*:5173", "apps/web/vite.config.ts"),
        ("shop", ResourceKind.DATABASE, "db://postgres/localhost:5432/shop_dev", ".env.example"),
        ("shop-login", ResourceKind.LISTEN_PORT, "tcp://*:5173", ".env.example"),
        ("shop-login", ResourceKind.LISTEN_PORT, "tcp://*:5173", "apps/web/vite.config.ts"),
        (
            "shop-login",
            ResourceKind.DATABASE,
            "db://postgres/localhost:5432/shop_dev",
            ".env.example",
        ),
        # the nested worktree is scanned once, as itself, never as part of the main one
        ("billing", ResourceKind.LISTEN_PORT, "tcp://*:5174", ".env.example"),
        ("billing", ResourceKind.LISTEN_PORT, "tcp://*:5173", "apps/web/vite.config.ts"),
    }
    assert snapshot.policy is not None


def test_the_command_marks_shared_resources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shop: Path
) -> None:
    assert _run(monkeypatch, "resources", "--repo", str(shop)) == 0
    out = _out(capsys)
    assert "3 worktrees, 3 resources, 2 used by more than one worktree" in out
    assert "tcp://*:5173 3 worktrees" in out
    assert "db://postgres/localhost:5432/shop_dev 2 worktrees" in out
    # worktree names use the platform's separator: shop\worktrees\billing on Windows
    assert re.search(r"shop[\\/]worktrees[\\/]billing \.env\.example:1 PORT=5174", out)


def test_a_prunable_worktree_is_left_out(shop: Path) -> None:
    shutil.rmtree(shop.parent / "shop-login")
    snapshot = inspect_resources(SubprocessRunner(), shop)
    assert {Path(c.worktree).name for c in snapshot.claims} == {"shop", "billing"}


def test_env_files_only_with_the_flag_and_never_their_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shop: Path
) -> None:
    (shop / ".env").write_text(
        f"DB_PASSWORD={CANARY}\nDATABASE_URL=postgres://u:{CANARY}/x@db/app\nAPI_PORT=9000\n",
        encoding="utf-8",
    )
    assert _run(monkeypatch, "resources", "--repo", str(shop)) == 0
    unread = _out(capsys)
    assert "9000" not in unread
    assert ".env was not read: .env files are read only with --include-env" in unread
    assert _run(monkeypatch, "resources", "--repo", str(shop), "--include-env") == 0
    out = _out(capsys)
    assert "tcp://*:9000" in out
    assert "Could not be identified" in out
    assert ".env:2 DATABASE_URL: it has an @ after the host part" in out
    assert CANARY not in out


def test_the_policy_can_opt_in_to_env_files(shop: Path) -> None:
    (shop / ".env").write_text("API_PORT=9001\n", encoding="utf-8")
    (shop / POLICY_FILE).write_text("schema_version = 1\n[scan]\ninclude_env_files = true\n")
    keys = {c.key for c in inspect_resources(SubprocessRunner(), shop).claims}
    assert "tcp://*:9001" in keys


def test_a_scan_writes_nothing_to_any_worktree_or_git(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shop: Path
) -> None:
    before = tree_digest(shop.parent)
    assert _run(monkeypatch, "resources", "--repo", str(shop), "--include-env") == 0
    assert tree_digest(shop.parent) == before


def test_skipped_files_are_listed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shop: Path
) -> None:
    (shop / POLICY_FILE).write_text("schema_version = 1\n[scan]\nmax_file_bytes = 10\n")
    assert _run(monkeypatch, "resources", "--repo", str(shop)) == 0
    out = _out(capsys)
    assert "Not read" in out
    assert ".env.example is larger than 10 bytes" in out


def test_errors_exit_2_and_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path, shop: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    assert _run(monkeypatch, "resources", "--repo", str(outside)) == 3
    (shop / POLICY_FILE).write_text("schema_version = 7\n")
    assert _run(monkeypatch, "resources", "--repo", str(shop)) == 2
    assert "schema_version 7 is not supported" in capsys.readouterr().err


def test_a_repository_without_configuration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path)
    assert _run(monkeypatch, "resources", "--repo", str(main)) == 0
    assert "No ports, databases or paths were found" in _out(capsys)


def _render(snapshot: Any) -> str:
    from rich.console import Console

    from worktree_shield.reports.terminal import render_resources

    console = Console(width=200, color_system=None)
    with console.capture() as capture:
        render_resources(snapshot, console)
    return " ".join(capture.get().split())


def test_failed_discovery_is_explained() -> None:
    failure = ProbeFailure("git worktree list", FailureKind.TIMEOUT, "git did not finish")
    out = _render(Snapshot("0.1.0", "t", probe_failures=(failure,)))
    assert "The worktrees could not be listed: git worktree list: git did not finish" in out


def test_one_worktree_at_the_root_and_redactions() -> None:
    repository = Repository("/.git", "/", False, (Worktree("/"),))
    claim = ResourceClaim(
        ResourceKind.LISTEN_PORT, "tcp://*:1", "/", SourceRef("/", "package.json"), "config.port=1"
    )
    snapshot = Snapshot(
        "0.1.0",
        "t",
        repository=repository,
        claims=(claim,),
        redactions=(RedactionCount("home_path", 2),),
    )
    out = _render(snapshot)
    assert "1 worktree, 1 resource, 0 used by more than one worktree" in out
    assert "named relative to" not in out
    assert "package.json config.port=1" in out  # no line number known
    assert "Redacted from this output: 2 home paths" in out


def test_a_listed_worktree_whose_directory_is_gone(
    monkeypatch: pytest.MonkeyPatch, shop: Path
) -> None:
    from worktree_shield.git.discovery import discover

    repository, _ = discover(SubprocessRunner(), shop)
    assert repository is not None
    gone = Worktree(str(shop.parent / "gone"))
    with_gone = Repository(
        repository.common_dir, repository.current, False, (*repository.worktrees, gone)
    )
    monkeypatch.setattr(
        "worktree_shield.orchestrator.discover", lambda runner, start: (with_gone, ())
    )
    snapshot = inspect_resources(SubprocessRunner(), shop)
    (skipped,) = snapshot.skipped
    assert (skipped.source.worktree, skipped.reason) == (
        gone.path,
        "is listed by Git but is not a directory",
    )


def test_discovery_failure_returns_the_snapshot_without_claims(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    failure = ProbeFailure("git worktree list", FailureKind.TIMEOUT, "slow")
    monkeypatch.setattr(
        "worktree_shield.orchestrator.discover", lambda runner, start: (None, (failure,))
    )
    snapshot = inspect_resources(SubprocessRunner(), tmp_path)
    assert (snapshot.repository, snapshot.policy, snapshot.claims) == (None, None, ())


def test_compose_projects_named_in_the_file_are_shared(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path, "shop")
    (main / "compose.yaml").write_text(
        "name: shop\nservices:\n  db:\n    image: postgres\n    container_name: shop-db\n"
        "    ports: ['5432:5432']\n    volumes: ['pgdata:/var/lib/postgresql/data']\n"
        "volumes:\n  pgdata: {}\n",
        encoding="utf-8",
    )
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "compose")
    add_worktree(main, tmp_path / "shop-login", "login")
    assert _run(monkeypatch, "resources", "--repo", str(main)) == 0
    out = _out(capsys)
    for shared in (
        "compose-project://shop 2 worktrees",
        "container://shop-db 2 worktrees",
        "tcp://*:5432 2 worktrees",
        "volume://shop_pgdata 2 worktrees",
    ):
        assert shared in out
    assert "Compose projects" in out


def test_a_running_server_shows_as_a_runtime_claim(shop: Path) -> None:
    from tests.fakes import FakeProcessTable

    login = shop.parent / "shop-login"
    table = FakeProcessTable(
        [("tcp", "127.0.0.1", 5173, 7), ("tcp", "0.0.0.0", 5173, None), ("tcp", "::", 9999, None)],
        {7: ("node", str(login / "apps" / "web"))},
        limitation="the sockets of other users' processes are listed without their owner",
    )
    snapshot = inspect_resources(SubprocessRunner(), shop, table=table)
    runtime = [c for c in snapshot.claims if c.source.path == "pid 7"]
    assert [(Path(c.worktree).name, c.key) for c in runtime] == [
        ("shop-login", "tcp://127.0.0.1:5173")
    ]
    assert snapshot.runtime is not None
    # only listeners on ports a worktree configures are kept: 5173, not 9999
    assert [(u.port, u.note) for u in snapshot.runtime.unattributed] == [
        (5173, "owned by a process of another user")
    ]
    assert snapshot.runtime.limitations == (
        "the sockets of other users' processes are listed without their owner",
    )
    from worktree_shield.collisions import find_collisions

    ports = [c for c in find_collisions(snapshot.claims) if c.key.endswith(":5173")]
    assert [c.certainty.value for c in ports] == ["confirmed"]


def test_runtime_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], shop: Path
) -> None:
    assert inspect_resources(SubprocessRunner(), shop, include_runtime=False).runtime is None
    assert _run(monkeypatch, "resources", "--repo", str(shop), "--no-runtime") == 0
    assert "Running processes were not looked at." in _out(capsys)


def test_a_failing_process_table_is_a_limitation(shop: Path) -> None:
    class Broken:
        def listening_sockets(self) -> Any:
            raise PermissionError(13, "Permission denied")

        def process(self, pid: int) -> Any:  # pragma: no cover - never reached
            raise AssertionError

    snapshot = inspect_resources(SubprocessRunner(), shop, table=Broken())
    assert snapshot.runtime is not None
    assert snapshot.runtime.limitations == (
        "running processes could not be listed ([Errno 13] Permission denied)",
    )


def test_listeners_outside_the_worktrees_are_shown(shop: Path) -> None:
    from rich.console import Console

    from tests.fakes import FakeProcessTable
    from worktree_shield.reports.terminal import render_resources

    table = FakeProcessTable(
        [("tcp", "::", 5173, 8), ("tcp", "0.0.0.0", 5173, None)],
        {8: ("code", "/elsewhere")},
        limitation="only the processes of the current user are visible",
    )
    snapshot = inspect_resources(SubprocessRunner(), shop, table=table)
    console = Console(width=300, color_system=None)
    with console.capture() as capture:
        render_resources(snapshot, console)
    out = " ".join(capture.get().split())
    assert "Configured ports in use outside the worktrees" in out
    assert "tcp [::]:5173 code (pid 8): it runs outside every worktree" in out
    assert "tcp 0.0.0.0:5173 a process: owned by a process of another user" in out
    assert "Running processes: only the processes of the current user are visible." in out
