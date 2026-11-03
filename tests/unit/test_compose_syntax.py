"""The ports and volumes syntax of the Compose specification (WTS-005)."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-005")


def _ports(entry: Any) -> Any:
    from worktree_shield.parsers.compose import published_ports

    result = published_ports(entry)
    return None if result is None else [(p.host_ip, p.port, p.protocol) for p in result]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("3000", []),  # container port only: Docker picks a free host port
        (3000, []),
        ("3000-3005", []),
        ("8000:8000", [(None, 8000, "tcp")]),
        ("9090-9091:8080-8081", [(None, 9090, "tcp"), (None, 9091, "tcp")]),
        ("49100:22", [(None, 49100, "tcp")]),
        ("127.0.0.1:8001:8001", [("127.0.0.1", 8001, "tcp")]),
        ("127.0.0.1:5000-5001:5000-5001", [("127.0.0.1", 5000, "tcp"), ("127.0.0.1", 5001, "tcp")]),
        ("127.0.0.1::5000", []),
        ("6060:6060/udp", [(None, 6060, "udp")]),
        ("[::1]:6001:6001", [("::1", 6001, "tcp")]),
        ("0.0.0.0:80:80/tcp", [("0.0.0.0", 80, "tcp")]),
        ({"target": 80, "published": 8080}, [(None, 8080, "tcp")]),
        (
            {"target": 80, "published": "8080", "host_ip": "127.0.0.1", "protocol": "udp"},
            [("127.0.0.1", 8080, "udp")],
        ),
        ({"target": 80, "published": "8080-8081"}, [(None, 8080, "tcp"), (None, 8081, "tcp")]),
        ({"target": 80}, []),
    ],
)
def test_published_ports(entry: Any, expected: Any) -> None:
    assert _ports(entry) == expected


@pytest.mark.parametrize(
    "entry",
    [
        "abc:80",
        "8000:",
        "70000:80",
        "8005-8000:80",
        "1-5000:1-5000",
        ":::",
        True,
        None,
        [1],
        {"published": "x"},
        "8000:80/http",
    ],
)
def test_unreadable_port_entries(entry: Any) -> None:
    assert _ports(entry) is None


def _mount(entry: Any) -> Any:
    from worktree_shield.parsers.compose import parse_mount

    mount = parse_mount(entry)
    return None if mount is None else (mount.kind, mount.source, mount.read_only)


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("/var/lib/data:/data", ("bind", "/var/lib/data", False)),
        ("/var/lib/data:/data:ro", ("bind", "/var/lib/data", True)),
        ("/var/lib/data:/data:ro,z", ("bind", "/var/lib/data", True)),
        ("./data:/data", ("bind", "./data", False)),
        ("../shared:/shared", ("bind", "../shared", False)),
        ("~/configs:/etc/configs", ("bind", "~/configs", False)),
        ("C:\\data:/data", ("bind", "C:\\data", False)),
        ("pgdata:/var/lib/postgresql/data", ("volume", "pgdata", False)),
        ("/just/a/target", ("volume", None, False)),  # anonymous volume
        (
            {"type": "bind", "source": "/srv/uploads", "target": "/uploads"},
            ("bind", "/srv/uploads", False),
        ),
        (
            {"type": "bind", "source": "/srv/x", "target": "/x", "read_only": True},
            ("bind", "/srv/x", True),
        ),
        ({"type": "volume", "source": "cache", "target": "/cache"}, ("volume", "cache", False)),
        ({"type": "tmpfs", "target": "/run/scratch"}, ("tmpfs", None, False)),
    ],
)
def test_mounts(entry: Any, expected: Any) -> None:
    assert _mount(entry) == expected


@pytest.mark.parametrize("entry", [3, None, {"type": "bind"}, {"type": 1, "source": "/x"}, ""])
def test_unreadable_mounts(entry: Any) -> None:
    assert _mount(entry) is None
