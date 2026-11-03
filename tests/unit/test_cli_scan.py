"""`worktree-shield scan` on real repositories (WTS-008, WTS-010, WTS-011)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.gitrepos import add_worktree, git, make_repo, tree_digest
from worktree_shield import cli
from worktree_shield.config import POLICY_FILE
from worktree_shield.models import (
    Confidence,
    FailureKind,
    Finding,
    Policy,
    ProbeFailure,
    Repository,
    Severity,
    Snapshot,
    Status,
    Worktree,
)
from worktree_shield.privacy import strip_control

CANARY = "Canary-Scan-55"


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["worktree-shield", *args])
    monkeypatch.setenv("COLUMNS", "300")
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    code = exit_info.value.code
    return code if isinstance(code, int) else 0


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(strip_control(capsys.readouterr().out).split())


def _repo(tmp_path: Path, second_port: int = 5173) -> Path:
    """Two worktrees with a shared database and, by default, a shared port."""
    main = make_repo(tmp_path, "app")
    (main / ".env.example").write_text(
        "PORT=5173\nDATABASE_URL=postgres://app:x@localhost:5432/app_dev\n", encoding="utf-8"
    )
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "env")
    login = add_worktree(main, tmp_path / "app-login", "login")
    (login / ".env.example").write_text(
        f"PORT={second_port}\nDATABASE_URL=postgres://app:x@localhost:5432/app_dev\n",
        encoding="utf-8",
    )
    return main


def test_a_shared_port_fails_only_with_strict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = _repo(tmp_path)
    assert _run(monkeypatch, "scan", "--repo", str(main), "--scope", "static") == 0
    out = _out(capsys)
    assert "FAIL WTS-PORT-001 Port 5173 is configured in 2 worktrees (probable)" in out
    assert "WARN WTS-DB-001 The Postgres database app_dev on localhost:5432 is used by 2" in out
    assert "app .env.example:1 PORT=5173" in out
    assert "Next: Give each worktree its own port" in out
    assert "policy: built-in defaults" in out
    assert "Read-only: nothing in the repository was run, changed or locked." in out
    assert _run(monkeypatch, "scan", "--repo", str(main), "--strict", "--scope", "static") == 1


def test_the_policy_decides_what_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = _repo(tmp_path)
    (main / POLICY_FILE).write_text("schema_version = 1\n[policy]\nshared_host_ports = 'warn'\n")
    assert _run(monkeypatch, "scan", "--repo", str(main), "--strict", "--scope", "static") == 0
    assert "WARN WTS-PORT-001" in _out(capsys)


def test_separate_ports_pass_strict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = _repo(tmp_path, second_port=5174)
    assert (
        _run(monkeypatch, "scan", "--repo", str(main), "--strict", "--all", "--scope", "static")
        == 0
    )
    out = _out(capsys)
    assert "PASS WTS-PORT-001 No port is configured in more than one worktree" in out
    assert "NOT TESTED WTS-PORT-002 Running processes were not looked at" in out
    assert "N/A WTS-DOCKER-001 No Compose file was found" in out


def test_without_all_the_rest_is_counted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = _repo(tmp_path, second_port=5174)
    assert _run(monkeypatch, "scan", "--repo", str(main), "--scope", "static") == 0
    assert "more checks passed or did not apply (--all lists them)" in _out(capsys)


LISTEN = (
    "import socket, time\n"
    "s = socket.socket()\n"
    "s.bind(('127.0.0.1', 0))\n"
    "s.listen()\n"
    "print(s.getsockname()[1], flush=True)\n"
    "time.sleep(60)\n"
)


@pytest.fixture
def running(tmp_path: Path) -> Iterator[tuple[Path, int]]:
    """A repository whose second worktree runs a server on the port the first configures."""
    main = make_repo(tmp_path, "app")
    login = add_worktree(main, tmp_path / "app-login", "login")
    server = subprocess.Popen(  # noqa: S603 - the test's own interpreter and program
        [sys.executable, "-c", LISTEN], cwd=login, stdout=subprocess.PIPE, text=True
    )
    try:
        assert server.stdout is not None
        port = int(server.stdout.readline())
        (main / ".env.example").write_text(f"HOST=127.0.0.1\nPORT={port}\n", encoding="utf-8")
        yield main, port
    finally:
        server.kill()
        server.wait(timeout=10)


def test_a_server_running_in_another_worktree_is_confirmed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], running: tuple[Path, int]
) -> None:
    main, port = running
    assert _run(monkeypatch, "scan", "--repo", str(main), "--strict") == 1
    out = _out(capsys)
    blocker = f"FAIL WTS-PORT-002 Port {port} is in use by a server running in another worktree"
    assert f"{blocker} (confirmed)" in out
    assert _run(monkeypatch, "scan", "--repo", str(main), "--scope", "runtime", "--all") == 0
    runtime_only = _out(capsys)
    assert "WTS-PORT-001" not in runtime_only
    assert "WTS-RUNTIME-001" in runtime_only


def test_a_scan_writes_nothing_and_shows_no_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = _repo(tmp_path)
    (main / ".env").write_text(
        f"DB_PASSWORD={CANARY}\nDATABASE_URL=postgres://u:{CANARY}@localhost/app_dev\n",
        encoding="utf-8",
    )
    before = tree_digest(tmp_path)
    assert _run(monkeypatch, "scan", "--repo", str(main), "--include-env", "--all") == 0
    assert CANARY not in capsys.readouterr().out
    assert tree_digest(tmp_path) == before


def test_errors_exit_2_and_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    assert _run(monkeypatch, "scan", "--repo", str(outside)) == 3
    main = _repo(tmp_path)
    (main / POLICY_FILE).write_text("schema_version = 1\n[policy]\nshared_ports = 'deny'\n")
    assert _run(monkeypatch, "scan", "--repo", str(main)) == 2
    assert "unknown key policy.shared_ports" in capsys.readouterr().err


def _render(snapshot: Any) -> str:
    from rich.console import Console

    from worktree_shield.reports.findings import render_scan

    console = Console(width=300, color_system=None)
    with console.capture() as capture:
        render_scan(snapshot, console)
    return " ".join(capture.get().split())


def _finding(rule: str, status: Status, summary: str, caused_by: str | None = None) -> Finding:
    return Finding(
        rule, status, Severity.MEDIUM, Confidence.MEDIUM, summary, "why", caused_by=caused_by
    )


def test_findings_that_follow_from_another_are_shown_under_it() -> None:
    repository = Repository("/r/.git", "/r", False, (Worktree("/r"),))
    findings = (
        _finding("WTS-DOCKER-001", Status.WARN, "Project shop is shared"),
        _finding("WTS-DOCKER-003", Status.WARN, "Volume shop_data is shared", "WTS-DOCKER-001"),
        _finding("WTS-PATH-001", Status.WARN, "Orphan follower", "WTS-PORT-001"),
    )
    policy = Policy(source="/r/.worktree-shield.toml")
    out = _render(Snapshot("0.1.0", "t", repository=repository, policy=policy, findings=findings))
    assert "policy: /r/.worktree-shield.toml" in out
    assert "Follows from it: WTS-DOCKER-003 Volume shop_data is shared" in out
    assert "WARN WTS-PATH-001 Orphan follower" in out  # its cause did not fire: shown on its own
    assert "Next:" not in out  # these findings have no action


def test_a_failed_discovery_is_explained_and_not_diagnosed() -> None:
    from worktree_shield.orchestrator import diagnose

    failure = ProbeFailure("git worktree list", FailureKind.TIMEOUT, "git did not finish")
    snapshot = Snapshot("0.1.0", "t", probe_failures=(failure,))
    assert diagnose(snapshot) is snapshot
    assert "The worktrees could not be listed: git worktree list: git did not finish" in _render(
        snapshot
    )
    from worktree_shield.reports.findings import counts_line

    assert counts_line(()) == "no findings"


def test_a_failed_discovery_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    failure = ProbeFailure("git worktree list", FailureKind.TIMEOUT, "slow")
    broken = Snapshot("0.1.0", "t", probe_failures=(failure,))
    monkeypatch.setattr(cli, "inspect_resources", lambda *args, **kwargs: broken)
    assert _run(monkeypatch, "scan", "--repo", str(tmp_path)) == 2
