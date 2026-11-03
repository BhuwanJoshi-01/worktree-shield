"""Whether two resource keys of the same kind name the same resource.

Keys keep what the configuration says (``tcp://*:5173``, ``tcp://127.0.0.1:5173``), so
equal strings are not the test: two listeners on the same port collide when one of
them binds every address. The rules here are the ones the collision graph uses.

Ports
    ``*`` (no host configured) and ``0.0.0.0`` bind every IPv4 address; ``::`` binds every
    address, IPv4 included, because Linux sockets are dual-stack by default
    (``net.ipv6.bindv6only = 0``). Two different addresses never collide; a host name
    *possibly* matches an address or another name, since it is resolved at start-up.
Databases
    ``localhost``, ``127.0.0.1`` and ``::1`` reach the same server. A database left to the
    default (``local``, no host) or a Unix socket is *possibly* that server, and an
    unknown database name (``?``) possibly any database on it.
Paths
    Compared after normalising ``.``, ``..`` and repeated separators, case-insensitively
    for Windows paths. One inside the other possibly overlaps (an output directory that
    holds another worktree's cache).
Names
    Compose projects, container names and volumes are equal or not.

Client endpoints never overlap: many clients share one server.
"""

from __future__ import annotations

import ipaddress
import ntpath
import posixpath
import re
from enum import Enum

from worktree_shield.models import ResourceKind


class Overlap(Enum):
    """``SAME`` resource for certain, ``POSSIBLE`` depending on what a name resolves to
    or how a path is used, or ``NONE``."""

    NONE = "none"
    POSSIBLE = "possible"
    SAME = "same"


_PORT_KEY = re.compile(r"([a-z]+)://(\[[^\]]*\]|[^:\[\]]*):([0-9]+)")
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_LOCAL = "local"
_IP = ipaddress.IPv4Address | ipaddress.IPv6Address


def overlap(kind: ResourceKind, a: str, b: str) -> Overlap:
    """How the resources behind keys ``a`` and ``b`` (both of ``kind``) overlap."""
    if kind is ResourceKind.CLIENT_ENDPOINT:
        return Overlap.NONE
    if kind is ResourceKind.LISTEN_PORT:
        return _ports(a, b)
    if kind is ResourceKind.DATABASE:
        return _databases(a, b)
    if kind is ResourceKind.ABSOLUTE_PATH:
        return _paths(a, b)
    return Overlap.SAME if a == b else Overlap.NONE


def _ports(a: str, b: str) -> Overlap:
    first, second = _PORT_KEY.fullmatch(a), _PORT_KEY.fullmatch(b)
    if first is None or second is None:
        return Overlap.SAME if a == b else Overlap.NONE
    if (first.group(1), first.group(3)) != (second.group(1), second.group(3)):
        return Overlap.NONE  # another protocol or port
    return _hosts(first.group(2).strip("[]"), second.group(2).strip("[]"))


def _hosts(a: str, b: str) -> Overlap:
    if a == b:
        return Overlap.SAME
    first, second = _address(a), _address(b)
    if _binds_all(first, second) or _binds_all(second, first):
        return Overlap.SAME
    if isinstance(first, _IP) and isinstance(second, _IP):
        return Overlap.NONE  # two distinct addresses
    if "localhost" in (a, b):
        other = second if a == "localhost" else first
        if isinstance(other, _IP):
            return Overlap.POSSIBLE if other.is_loopback else Overlap.NONE
    return Overlap.POSSIBLE  # a host name: it resolves only when the server starts


def _binds_all(this: _IP | str, other: _IP | str) -> bool:
    """Whether a listener on ``this`` also takes ``other``'s address."""
    if this == "*" or this == ipaddress.ip_address("::"):
        return True
    ipv4_any = ipaddress.ip_address("0.0.0.0")  # noqa: S104
    return this == ipv4_any and (other == "*" or isinstance(other, ipaddress.IPv4Address))


def _address(host: str) -> _IP | str:
    if host in {"", "*"}:
        return "*"
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return host


def _databases(a: str, b: str) -> Overlap:
    first, second = _database(a), _database(b)
    if first is None or second is None:
        return Overlap.SAME if a == b else Overlap.NONE
    if first[0] != second[0] or first[2] != second[2]:
        return Overlap.NONE  # another engine or port
    if first[0] == "sqlite":
        return Overlap.SAME if first[3] == second[3] else Overlap.NONE
    server = _servers(first[1], second[1])
    if server is Overlap.NONE:
        return server
    if first[3] == "?" or second[3] == "?":
        return Overlap.POSSIBLE
    if first[3] != second[3]:
        return Overlap.NONE
    return server


def _database(key: str) -> tuple[str, str, str, str] | None:
    """``db://engine/server:port/database`` as (engine, server, port, database)."""
    if not key.startswith("db://"):
        return None
    engine, _, rest = key[len("db://") :].partition("/")
    if engine == "sqlite":
        return engine, "", "", posixpath.normpath(rest)
    address, _, database = rest.rpartition("/")
    server, colon, port = address.rpartition(":")
    if not colon or not port.isdigit():
        server, port = address, ""
    return engine, server.strip("[]") if server.startswith("[") else server, port, database


def _servers(a: str, b: str) -> Overlap:
    if a == b or (a in _LOOPBACK and b in _LOOPBACK):
        return Overlap.SAME
    if a.startswith("unix:") and b.startswith("unix:"):
        return Overlap.NONE  # two socket directories, two servers
    if _is_local(a) and _is_local(b):
        return Overlap.POSSIBLE  # the default local server, by socket or by TCP
    return Overlap.NONE


def _is_local(server: str) -> bool:
    return server == _LOCAL or server in _LOOPBACK or server.startswith("unix:")


def _paths(a: str, b: str) -> Overlap:
    first, second = _path(a), _path(b)
    if first == second:
        return Overlap.SAME
    separator = "\\" if "\\" in first or "\\" in second else "/"
    if first.startswith(second.rstrip(separator) + separator) or second.startswith(
        first.rstrip(separator) + separator
    ):
        return Overlap.POSSIBLE
    return Overlap.NONE


def _path(key: str) -> str:
    path = key.removeprefix("path://")
    if re.match(r"[A-Za-z]:[\\/]", path):
        return ntpath.normcase(ntpath.normpath(path))
    return posixpath.normpath(path)


def path_within(key: str, directory: str) -> bool:
    """Whether the path of ``key`` (``path://…``) is ``directory`` or lies inside it."""
    path, root = _path(key), _path(f"path://{directory}")
    separator = "\\" if "\\" in path or "\\" in root else "/"
    return path == root or path.startswith(root.rstrip(separator) + separator)
