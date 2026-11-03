"""When two claims name the same resource (S6 normalisation)."""

from __future__ import annotations

import pytest


def _overlap(kind: str, a: str, b: str) -> str:
    from worktree_shield.models import ResourceKind
    from worktree_shield.overlap import overlap

    return overlap(ResourceKind(kind), a, b).value


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("tcp://*:5173", "tcp://*:5173", "same"),
        ("tcp://*:5173", "tcp://127.0.0.1:5173", "same"),  # unknown host: binds everything
        ("tcp://0.0.0.0:8000", "tcp://127.0.0.1:8000", "same"),
        ("tcp://0.0.0.0:8000", "tcp://[::1]:8000", "none"),  # IPv4 wildcard, IPv6 address
        ("tcp://[::]:8000", "tcp://127.0.0.1:8000", "same"),  # dual-stack by default on Linux
        ("tcp://127.0.0.1:8000", "tcp://127.0.0.1:8000", "same"),
        ("tcp://127.0.0.1:8000", "tcp://127.0.0.2:8000", "none"),
        ("tcp://localhost:8000", "tcp://127.0.0.1:8000", "possible"),
        ("tcp://localhost:8000", "tcp://[::1]:8000", "possible"),
        ("tcp://dev.local:8000", "tcp://dev.local:8000", "same"),
        ("tcp://dev.local:8000", "tcp://other.local:8000", "possible"),
        ("tcp://dev.local:8000", "tcp://127.0.0.1:8000", "possible"),
        ("tcp://*:8000", "tcp://*:8001", "none"),
        ("tcp://*:8000", "udp://*:8000", "none"),
        ("udp://*:53", "udp://0.0.0.0:53", "same"),
        ("tcp://0.0.0.0:80", "tcp://dev.local:80", "possible"),
        ("tcp://localhost:80", "tcp://10.0.0.5:80", "none"),
        ("tcp://localhost:80", "tcp://dev.local:80", "possible"),
        ("odd", "odd", "same"),
        ("odd", "tcp://*:80", "none"),
    ],
)
def test_listen_ports(a: str, b: str, expected: str) -> None:
    assert _overlap("listen_port", a, b) == expected
    assert _overlap("listen_port", b, a) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("db://postgres/localhost:5432/app", "db://postgres/localhost:5432/app", "same"),
        ("db://postgres/localhost:5432/app", "db://postgres/127.0.0.1:5432/app", "same"),
        ("db://postgres/localhost:5432/app", "db://postgres/[::1]:5432/app", "same"),
        ("db://postgres/localhost:5432/app", "db://postgres/local:5432/app", "possible"),
        ("db://postgres/localhost:5432/app", "db://postgres/localhost:5432/other", "none"),
        ("db://postgres/localhost:5432/app", "db://postgres/localhost:5433/app", "none"),
        ("db://postgres/localhost:5432/app", "db://mysql/localhost:5432/app", "none"),
        ("db://postgres/localhost:5432/?", "db://postgres/localhost:5432/app", "possible"),
        ("db://postgres/db.internal:5432/app", "db://postgres/db.other:5432/app", "none"),
        ("db://redis/localhost:6379/0", "db://redis/localhost:6379/1", "none"),
        ("db://sqlite//srv/app.db", "db://sqlite//srv/./app.db", "same"),
        ("db://postgres/unix:/run/pg:5432/app", "db://postgres/local:5432/app", "possible"),
        ("db://postgres/unix:/run/a:5432/app", "db://postgres/unix:/run/b:5432/app", "none"),
        ("db://mongodb/a:1,b:2/blog", "db://mongodb/a:1,b:2/blog", "same"),
        ("db://mongodb/cluster.example/blog", "db://mongodb/cluster.example/blog", "same"),
        ("not-a-db-key", "not-a-db-key", "same"),
    ],
)
def test_databases(a: str, b: str, expected: str) -> None:
    assert _overlap("database", a, b) == expected
    assert _overlap("database", b, a) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("path:///srv/cache", "path:///srv/cache", "same"),
        ("path:///srv/cache", "path:///srv//cache/.", "same"),
        ("path:///srv/cache", "path:///srv/cache/images", "possible"),  # one inside the other
        ("path:///srv/cache", "path:///srv/cache2", "none"),
        ("path:///srv/a/../cache", "path:///srv/cache", "same"),
        ("path://C:\\Data\\Cache", "path://c:/data/cache", "same"),
        ("path://~/.cache/shop", "path://~/.cache/shop", "same"),
    ],
)
def test_paths(a: str, b: str, expected: str) -> None:
    assert _overlap("absolute_path", a, b) == expected
    assert _overlap("absolute_path", b, a) == expected


@pytest.mark.parametrize("kind", ["compose_project", "container_name", "volume"])
def test_names_overlap_only_when_equal(kind: str) -> None:
    assert _overlap(kind, "x://shop", "x://shop") == "same"
    assert _overlap(kind, "x://shop", "x://shop-login") == "none"


def test_client_endpoints_never_overlap() -> None:
    assert _overlap("client_endpoint", "tcp://localhost:5432", "tcp://localhost:5432") == "none"
