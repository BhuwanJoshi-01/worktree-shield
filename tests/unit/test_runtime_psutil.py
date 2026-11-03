"""The real process table, on this machine and with psutil's failures simulated."""

from __future__ import annotations

import socket
import subprocess
import sys
from collections import namedtuple
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psutil
import pytest

from worktree_shield.collectors import runtime
from worktree_shield.collectors.runtime import (
    ProcessDeniedError,
    ProcessGoneError,
    PsutilTable,
    observe_runtime,
)

LISTEN_ONCE = (
    "import socket, sys, time\n"
    "s = socket.socket()\n"
    "s.bind(('127.0.0.1', 0))\n"
    "s.listen()\n"
    "print(s.getsockname()[1], flush=True)\n"
    "time.sleep(60)\n"
)


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[Path, int]]:
    """A real listener whose working directory is a fresh directory."""
    worktree = tmp_path / "wt"
    (worktree / "app").mkdir(parents=True)
    process = subprocess.Popen(  # noqa: S603 - the test's own interpreter and program
        [sys.executable, "-c", LISTEN_ONCE],
        cwd=worktree / "app",
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        port = int(process.stdout.readline())
        yield worktree, port
    finally:
        process.kill()
        process.wait(timeout=10)


def test_a_real_server_is_tied_to_its_worktree(server: tuple[Path, int]) -> None:
    worktree, port = server
    claims, _, _ = observe_runtime(PsutilTable(), [str(worktree)])
    keys = {c.key for c in claims}
    assert f"tcp://127.0.0.1:{port}" in keys
    (claim,) = [c for c in claims if c.key == f"tcp://127.0.0.1:{port}"]
    assert claim.detail.startswith(("python", "Python"))


def test_the_current_process_can_be_looked_up() -> None:
    name, cwd = PsutilTable().process(psutil.Process().pid)
    assert name
    assert cwd is not None


Conn = namedtuple("Conn", "fd family type laddr raddr status pid")
Addr = namedtuple("Addr", "ip port")


@pytest.mark.parametrize(
    ("connection", "expected"),
    [
        (
            Conn(3, 2, socket.SOCK_STREAM, Addr("127.0.0.1", 80), (), "LISTEN", 9),
            ("tcp", "127.0.0.1", 80, 9),
        ),
        (
            Conn(
                3,
                2,
                socket.SOCK_STREAM,
                Addr("127.0.0.1", 80),
                Addr("1.2.3.4", 5),
                "ESTABLISHED",
                9,
            ),
            None,
        ),
        (
            Conn(3, 2, socket.SOCK_DGRAM, Addr("0.0.0.0", 53), (), "NONE", None),
            ("udp", "0.0.0.0", 53, None),
        ),
        (Conn(3, 2, socket.SOCK_DGRAM, Addr("0.0.0.0", 53), Addr("1.1.1.1", 53), "NONE", 1), None),
        (
            Conn(3, 10, socket.SOCK_STREAM, Addr("fe80::1%eth0", 22), (), "LISTEN", 1),
            ("tcp", "fe80::1", 22, 1),
        ),
        (Conn(3, 2, socket.SOCK_STREAM, (), (), "LISTEN", 1), None),
    ],
)
def test_sockets_from_connections(connection: Any, expected: Any) -> None:
    found = runtime._socket(connection, connection.pid)
    assert (
        None if found is None else (found.protocol, found.address, found.port, found.pid)
    ) == expected


def test_without_access_to_every_socket_own_processes_are_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    PConn = namedtuple("PConn", "fd family type laddr raddr status")

    class Own:
        pid = 42

        def net_connections(self, kind: str) -> list[Any]:
            return [PConn(3, 2, socket.SOCK_STREAM, Addr("127.0.0.1", 3000), (), "LISTEN")]

    class Gone:
        pid = 43

        def net_connections(self, kind: str) -> list[Any]:
            raise psutil.NoSuchProcess(43)

    def denied(kind: str) -> list[Any]:
        raise psutil.AccessDenied

    monkeypatch.setattr(runtime.psutil, "net_connections", denied)
    monkeypatch.setattr(runtime.psutil, "process_iter", lambda: [Own(), Gone()])
    sockets, limitation = PsutilTable().listening_sockets()
    assert [(s.port, s.pid) for s in sockets] == [(3000, 42)]
    assert limitation == "only the processes of the current user are visible"


def test_hidden_owners_are_a_limitation(monkeypatch: pytest.MonkeyPatch) -> None:
    hidden = Conn(3, 2, socket.SOCK_STREAM, Addr("0.0.0.0", 5432), (), "LISTEN", None)
    monkeypatch.setattr(runtime.psutil, "net_connections", lambda kind: [hidden])
    _, limitation = PsutilTable().listening_sockets()
    assert limitation == "the sockets of other users' processes are listed without their owner"


@pytest.mark.parametrize(
    ("error", "expected"),
    [(psutil.NoSuchProcess(1), ProcessGoneError), (psutil.AccessDenied(1), ProcessDeniedError)],
)
def test_process_failures(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: type
) -> None:
    def broken(pid: int) -> Any:
        raise error

    monkeypatch.setattr(runtime.psutil, "Process", broken)
    with pytest.raises(expected):
        PsutilTable().process(1)


def test_an_unreadable_working_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    class Private:
        def __init__(self, pid: int) -> None:
            pass

        def name(self) -> str:
            return "postgres"

        def cwd(self) -> str:
            raise psutil.AccessDenied

    monkeypatch.setattr(runtime.psutil, "Process", Private)
    assert PsutilTable().process(1) == ("postgres", None)
