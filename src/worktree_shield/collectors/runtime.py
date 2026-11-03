"""Listening processes, tied to a worktree only by their working directory.

Read-only and without privileges: the listening sockets the system shows, and for each
owning process its name and working directory. Never its command line or environment,
which can hold secrets, and nothing is signalled. A process name like ``node`` says
nothing about the worktree, so it is never used to attribute one; a listener that
cannot be tied is kept with the reason, because it may still hold a port a worktree
needs.

The view is a snapshot: a server started a second later is not seen. On Linux the
sockets of other users' processes are listed without their owner; on macOS only the
current user's processes are visible.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from socket import SOCK_DGRAM, SOCK_STREAM
from typing import Any, Protocol

import psutil

from worktree_shield.collectors.base import port_key
from worktree_shield.models import Listener, Observation, ResourceClaim, ResourceKind, SourceRef


@dataclass(frozen=True, slots=True)
class Socket:
    """A listening (TCP) or bound (UDP) local socket and the process owning it."""

    protocol: str
    address: str
    port: int
    pid: int | None


class ProcessGoneError(Exception):
    """The process ended while it was looked at."""


class ProcessDeniedError(Exception):
    """The process cannot be inspected without more privileges."""


class ProcessTable(Protocol):
    def listening_sockets(self) -> tuple[list[Socket], str | None]:
        """The sockets, and what limited the view (``None`` when nothing did)."""
        ...

    def process(self, pid: int) -> tuple[str, str | None]:
        """Name and working directory (``None`` if unreadable) of a process."""
        ...


def observe_runtime(
    table: ProcessTable, worktrees: Sequence[str]
) -> tuple[list[ResourceClaim], list[Listener], list[str]]:
    """Runtime claims of the worktrees, the listeners no worktree owns, and the
    limitations of the view."""
    sockets, limitation = table.listening_sockets()
    roots = sorted(((_canonical(w), w) for w in worktrees), key=lambda r: len(r[0]), reverse=True)
    looked_up: dict[int, tuple[str | None, str | None, str | None]] = {}
    claims: list[ResourceClaim] = []
    unattributed: list[Listener] = []
    for socket in sockets:
        if socket.pid is None:
            unattributed.append(_listener(socket, None, "owned by a process of another user"))
            continue
        if socket.pid not in looked_up:
            looked_up[socket.pid] = _look_up(table, socket.pid, roots)
        name, worktree, note = looked_up[socket.pid]
        if worktree is None:
            unattributed.append(_listener(socket, name, note or ""))
            continue
        key = port_key(socket.address, socket.port, protocol=socket.protocol)
        source = SourceRef(worktree, f"pid {socket.pid}")
        detail = f"{name} (pid {socket.pid}) is listening; it runs in this worktree"
        claims.append(
            ResourceClaim(
                ResourceKind.LISTEN_PORT, key, worktree, source, detail, Observation.RUNTIME
            )
        )
    return claims, unattributed, [limitation] if limitation else []


def _look_up(
    table: ProcessTable, pid: int, roots: list[tuple[str, str]]
) -> tuple[str | None, str | None, str | None]:
    """(name, worktree, note): the worktree it runs in, or why there is none."""
    try:
        name, cwd = table.process(pid)
    except ProcessGoneError:
        return None, None, "the process ended while it was looked at"
    except ProcessDeniedError:
        return None, None, "the process cannot be inspected without more privileges"
    if cwd is None:
        return name, None, "its working directory cannot be read"
    directory = _canonical(cwd)
    for root, worktree in roots:  # deepest first: nested worktrees
        if directory == root or directory.startswith(root.rstrip(os.sep) + os.sep):
            return name, worktree, None
    return name, None, "it runs outside every worktree"


def _listener(socket: Socket, process: str | None, note: str) -> Listener:
    return Listener(socket.protocol, socket.address, socket.port, socket.pid, process, note)


def _canonical(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


class PsutilTable:
    """The real process table, through psutil."""

    def listening_sockets(self) -> tuple[list[Socket], str | None]:
        found: list[Socket | None]
        try:
            found = [_socket(c, c.pid) for c in psutil.net_connections(kind="inet")]
            limitation = None
        except psutil.AccessDenied:  # macOS: only the current user's processes
            found = []
            for process in psutil.process_iter():
                try:
                    found += [_socket(c, process.pid) for c in process.net_connections(kind="inet")]
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
            limitation = "only the processes of the current user are visible"
        listening = [s for s in found if s is not None]
        if limitation is None and any(s.pid is None for s in listening):
            limitation = "the sockets of other users' processes are listed without their owner"
        return listening, limitation

    def process(self, pid: int) -> tuple[str, str | None]:
        try:
            process = psutil.Process(pid)
            name = process.name()
            try:
                cwd: str | None = process.cwd()
            except psutil.AccessDenied:
                cwd = None
            return name, cwd or None
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            raise ProcessGoneError from None
        except psutil.AccessDenied:
            raise ProcessDeniedError from None


def _socket(connection: Any, pid: int | None) -> Socket | None:
    """A listening TCP or bound, unconnected UDP socket; ``None`` for anything else.
    ``connection`` is a psutil ``sconn`` or ``pconn``; only the fields both have are used."""
    if not connection.laddr:
        return None
    if connection.type == SOCK_STREAM:
        if connection.status != psutil.CONN_LISTEN:
            return None
        protocol = "tcp"
    elif connection.type == SOCK_DGRAM:
        if connection.raddr:
            return None
        protocol = "udp"
    else:  # pragma: no cover - kind="inet" lists only TCP and UDP
        return None
    address, port = connection.laddr.ip, connection.laddr.port
    return Socket(protocol, address.split("%", 1)[0], port, pid)
