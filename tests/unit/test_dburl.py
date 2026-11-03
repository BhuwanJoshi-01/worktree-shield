"""Database URLs reduced to engine, host, port and database; credentials dropped (WTS-004)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-004")

SECRET = "S3cr3t-Canary"


def _parse(url: str) -> Any:
    from worktree_shield.parsers.dburl import parse_database_url

    return parse_database_url(url)


def _target(engine: str, host: Any, port: Any, database: Any, socket: Any = None) -> Any:
    from worktree_shield.parsers.dburl import DatabaseTarget

    return DatabaseTarget(engine, host, port, database, socket)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            f"postgres://app:{SECRET}@localhost:5432/app_dev",
            ("postgres", "localhost", 5432, "app_dev"),
        ),
        ("postgresql://db.internal/app", ("postgres", "db.internal", 5432, "app")),
        (
            f"postgresql+psycopg://app:{SECRET}@DB.Local:6543/App",
            ("postgres", "db.local", 6543, "App"),
        ),
        ("postgresql+asyncpg://localhost/app", ("postgres", "localhost", 5432, "app")),
        ("jdbc:postgresql://localhost:5432/app", ("postgres", "localhost", 5432, "app")),
        ("postgres://[::1]:5433/app", ("postgres", "::1", 5433, "app")),
        ("postgres://localhost/app%20dev", ("postgres", "localhost", 5432, "app dev")),
        (f"mysql://root:{SECRET}@127.0.0.1/shop", ("mysql", "127.0.0.1", 3306, "shop")),
        ("mysql+pymysql://localhost:3307/shop", ("mysql", "localhost", 3307, "shop")),
        ("mariadb://localhost/shop", ("mysql", "localhost", 3306, "shop")),
        ("redis://localhost:6379/2", ("redis", "localhost", 6379, "2")),
        ("redis://localhost", ("redis", "localhost", 6379, "0")),
        (f"rediss://:{SECRET}@cache.example:6380", ("redis", "cache.example", 6380, "0")),
        ("redis://localhost/?db=3", ("redis", "localhost", 6379, "3")),
        (f"mongodb://u:{SECRET}@localhost/blog", ("mongodb", "localhost", 27017, "blog")),
        (
            "mongodb+srv://cluster0.example.net/blog",
            ("mongodb", "cluster0.example.net", None, "blog"),
        ),
        (
            "mongodb://b.example:27018,a.example:27017/blog?replicaSet=rs0",
            ("mongodb", "a.example:27017,b.example:27018", None, "blog"),
        ),
        ("postgres://localhost:5432", ("postgres", "localhost", 5432, None)),
        ("postgres://", ("postgres", None, 5432, None)),
    ],
)
def test_server_urls(url: str, expected: tuple[Any, ...]) -> None:
    assert _parse(url) == _target(*expected)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql:///app?host=/var/run/postgresql",
            ("postgres", None, 5432, "app", "/var/run/postgresql"),
        ),
        (
            "postgresql://%2Fvar%2Frun%2Fpostgresql/app",
            ("postgres", None, 5432, "app", "/var/run/postgresql"),
        ),
        ("postgres://localhost/app?port=5440", ("postgres", "localhost", 5440, "app", None)),
    ],
)
def test_postgres_sockets_and_query_parameters(url: str, expected: tuple[Any, ...]) -> None:
    assert _parse(url) == _target(*expected)


@pytest.mark.parametrize(
    ("url", "database"),
    [
        ("sqlite:////srv/data/app.db", "/srv/data/app.db"),
        ("sqlite:///data/app.db", "data/app.db"),
        ("sqlite+aiosqlite:///./app.db", "./app.db"),
    ],
)
def test_sqlite_keeps_the_path(url: str, database: str) -> None:
    assert _parse(url) == _target("sqlite", None, None, database)


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///:memory:"])
def test_sqlite_in_memory_is_no_shared_resource(url: str) -> None:
    assert _parse(url) is None


@pytest.mark.parametrize(
    "url",
    ["https://example.com/app", "amqp://localhost", "file:///srv/db", "localhost:5432", "", "5432"],
)
def test_other_values_are_not_databases(url: str) -> None:
    assert _parse(url) is None


@pytest.mark.parametrize(
    "url",
    [
        f"postgres://app:{SECRET}/x@db.internal/app",  # unencoded / in the password
        f"postgres://app:pa#{SECRET}@db.internal/app",  # unencoded # in the password
        f"postgres://app:pa?{SECRET}@db.internal/app",  # unencoded ? in the password
        "postgres://localhost:99999/app",
        "postgres://localhost:port/app",
        "postgres://a:5432,b:5433/app",  # libpq multi-host
        "postgres://${DB_HOST}:5432/app",
    ],
)
def test_urls_that_cannot_be_read_safely(url: str) -> None:
    from worktree_shield.parsers.dburl import DatabaseURLError

    with pytest.raises(DatabaseURLError) as caught:
        _parse(url)
    assert SECRET not in str(caught.value)
    assert "postgres://" not in str(caught.value)  # the URL is never echoed


def test_credentials_never_reach_the_result() -> None:
    target = _parse(f"postgres://admin:{SECRET}@{SECRET.lower()}x.local/app")
    assert SECRET not in repr(target)
    assert "admin" not in repr(target)


def test_the_key_identifies_the_server_and_database() -> None:
    from worktree_shield.parsers.dburl import DatabaseTarget

    assert _parse("postgres://localhost/app_dev").key == "db://postgres/localhost:5432/app_dev"
    assert _parse("redis://localhost/1").key == "db://redis/localhost:6379/1"
    sock = _parse("postgresql:///app?host=/run/pg")
    assert sock.key == "db://postgres/unix:/run/pg:5432/app"
    assert DatabaseTarget("postgres", None, 5432, None).key == "db://postgres/local:5432/?"


@given(st.text(max_size=200))
def test_any_value_is_parsed_or_refused_without_echoing_it(value: str) -> None:
    from worktree_shield.parsers.dburl import DatabaseURLError, parse_database_url

    message = ""
    try:
        parse_database_url(value)
    except DatabaseURLError as error:
        message = str(error)
    assert len(value) < 12 or value not in message
