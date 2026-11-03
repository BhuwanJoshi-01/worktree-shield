"""The ``ports`` and ``volumes`` syntax of the Compose specification.

Only what decides a collision is extracted: the host ports a service publishes (two
stacks publishing the same host port cannot run at once) and the host paths and named
volumes it mounts. Values must already be interpolated. An entry that is not valid
Compose comes back as ``None`` so a report can say it was not understood, rather than
as a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from worktree_shield.names import literal_host, port_number

MAX_RANGE = 256  # ports in one published range; a wider one is reported as unreadable
_PROTOCOLS = frozenset({"tcp", "udp", "sctp"})
_RANGE = re.compile(r"([0-9]{1,5})(?:-([0-9]{1,5}))?")
_WINDOWS_SOURCE = re.compile(r"[A-Za-z]:[\\/]")


@dataclass(frozen=True, slots=True)
class PublishedPort:
    """A host port a service publishes. ``host_ip`` is as written (``0.0.0.0`` stays);
    ``None`` means no address was given, which also publishes on every address."""

    host_ip: str | None
    port: int
    protocol: str = "tcp"


@dataclass(frozen=True, slots=True)
class Mount:
    """One entry of a service's ``volumes``. ``source`` is a host path for ``bind``, a
    volume name for ``volume`` (``None`` for an anonymous one), ``None`` for ``tmpfs``."""

    kind: str
    source: str | None
    read_only: bool = False


def published_ports(entry: Any) -> list[PublishedPort] | None:
    """The host ports a ``ports`` entry publishes: empty when Docker picks a free one,
    ``None`` when the entry is not valid."""
    if isinstance(entry, bool):
        return None
    if isinstance(entry, int):
        return [] if port_number(str(entry)) is not None else None
    if isinstance(entry, str):
        return _short_ports(entry.strip())
    if isinstance(entry, dict):
        return _long_ports(entry)
    return None


def _short_ports(text: str) -> list[PublishedPort] | None:
    """``[[IP:]HOST:]CONTAINER[/PROTOCOL]``, ports or ranges, IPv6 in brackets."""
    text, _, protocol = text.partition("/")
    protocol = protocol or "tcp"
    if protocol not in _PROTOCOLS:
        return None
    host_ip: str | None = None
    if text.startswith("["):
        address, bracket, text = text[1:].partition("]")
        if not bracket or not text.startswith(":"):
            return None
        host_ip, text = literal_host(address), text[1:]
        if host_ip is None:
            return None
    parts = text.split(":")
    if len(parts) == 3 and host_ip is None:
        host_ip = literal_host(parts[0])
        if host_ip is None:
            return None
        parts = parts[1:]
    if len(parts) == 1:
        return [] if _ports(parts[0]) else None  # container port only
    if len(parts) != 2 or _ports(parts[1]) is None:
        return None
    if parts[0] == "":
        return []  # 127.0.0.1::5000: a free host port on that address
    host_ports = _ports(parts[0])
    if host_ports is None:
        return None
    return [PublishedPort(host_ip, port, protocol) for port in host_ports]


def _long_ports(entry: dict[str, Any]) -> list[PublishedPort] | None:
    published = entry.get("published")
    if published is None:
        return [] if "target" in entry else None
    if isinstance(published, bool) or not isinstance(published, (int, str)):
        return None
    host_ports = _ports(str(published))
    protocol = entry.get("protocol", "tcp")
    host_ip = entry.get("host_ip")
    if host_ports is None or protocol not in _PROTOCOLS:
        return None
    if host_ip is not None and (not isinstance(host_ip, str) or literal_host(host_ip) is None):
        return None
    address = literal_host(host_ip) if isinstance(host_ip, str) else None
    return [PublishedPort(address, port, protocol) for port in host_ports]


def _ports(text: str) -> list[int] | None:
    """``8000`` or ``8000-8005`` as a list of ports; ``None`` if not valid."""
    match = _RANGE.fullmatch(text)
    if match is None:
        return None
    first = port_number(match.group(1))
    last = port_number(match.group(2)) if match.group(2) else first
    if first is None or last is None or last < first or last - first >= MAX_RANGE:
        return None
    return list(range(first, last + 1))


def parse_mount(entry: Any) -> Mount | None:
    """One ``volumes`` entry of a service, short or long syntax; ``None`` if not valid."""
    if isinstance(entry, str):
        return _short_mount(entry.strip())
    if isinstance(entry, dict):
        kind = entry.get("type", "volume")
        source = entry.get("source")
        if not isinstance(kind, str) or (source is not None and not isinstance(source, str)):
            return None
        if kind == "bind" and not source:
            return None
        return Mount(kind, source or None, entry.get("read_only") is True)
    return None


def _short_mount(text: str) -> Mount | None:
    """``[SOURCE:]TARGET[:MODE]``; a source that looks like a path is a bind mount."""
    if not text:
        return None
    drive = ""
    if _WINDOWS_SOURCE.match(text):
        drive, text = text[:2], text[2:]
    parts = text.split(":")
    if len(parts) == 1:
        return Mount("volume", None) if not drive else None  # anonymous volume
    source, mode = drive + parts[0], parts[2] if len(parts) > 2 else ""
    read_only = "ro" in mode.split(",")
    if drive or source.startswith(("/", ".", "~")):
        return Mount("bind", source, read_only)
    return Mount("volume", source, read_only)
