"""`worktree-shield resources` on real repositories (WTS-003, WTS-004, WTS-006, WTS-012)."""

from __future__ import annotations

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
    assert "shop/worktrees/billing .env.example:1 PORT=5174" in out
    assert ".env and .env.local were not read" in out


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
    assert "9000" not in capsys.readouterr().out
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
