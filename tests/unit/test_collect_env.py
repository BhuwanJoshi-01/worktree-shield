"""Resources declared in .env files (WTS-003, WTS-004, WTS-006)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from tests.fakes import read_fixture
from worktree_shield.models import Policy, ResourceKind

CANARY = "Canary-Pw-91"


def _collect(root: Path, policy: Policy | None = None, directory: str = "") -> Any:
    from worktree_shield.collectors.base import Collected, Scope
    from worktree_shield.collectors.envfiles import collect_env_files

    out = Collected()
    scope = Scope(root, "/repos/app", (policy or Policy()).max_file_bytes)
    collect_env_files(scope, PurePosixPath(directory), policy or Policy(), out)
    return out


def _claims(out: Any) -> set[tuple[str, str, str, int | None]]:
    return {(c.kind.value, c.key, c.source.path, c.source.line) for c in out.claims}


def test_the_example_file(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(read_fixture("env", "example.env"))
    out = _collect(tmp_path)
    assert _claims(out) == {
        ("listen_port", "tcp://*:5173", ".env.example", 4),
        ("listen_port", "tcp://*:8080", ".env.example", 5),
        ("database", "db://postgres/localhost:5432/app_dev", ".env.example", 8),
        ("database", "db://redis/localhost:6379/0", ".env.example", 9),
        ("absolute_path", "path:///tmp/app-cache", ".env.example", 10),
    }
    assert out.skipped == []
    assert out.unreadable == []
    assert all(c.worktree == "/repos/app" for c in out.claims)


def test_a_host_next_to_a_port_narrows_the_listener(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "HOST=127.0.0.1\nPORT=3000\nAPI_HOST=0.0.0.0\nAPI_PORT=8000\n"
    )
    keys = {c.key for c in _collect(tmp_path).claims}
    assert keys == {"tcp://127.0.0.1:3000", "tcp://0.0.0.0:8000"}


def test_ports_of_servers_the_app_connects_to_are_client_endpoints(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "DB_HOST=db.local\nDB_PORT=5432\nREDIS_PORT=6379\nPGPORT=5433\nNEXT_PUBLIC_DB_PORT=1\n"
    )
    claims = {(c.kind, c.key) for c in _collect(tmp_path).claims}
    assert claims == {
        (ResourceKind.CLIENT_ENDPOINT, "tcp://db.local:5432"),
        (ResourceKind.CLIENT_ENDPOINT, "tcp://localhost:6379"),
        (ResourceKind.CLIENT_ENDPOINT, "tcp://localhost:5433"),
        (ResourceKind.CLIENT_ENDPOINT, "tcp://localhost:1"),
    }


@pytest.mark.parametrize(
    "line",
    ["PORT=abc", "PORT=0", "PORT=70000", "PORT=${APP_PORT}", "PORT=", "SUPPORT=1", "PORTS=1"],
)
def test_values_that_are_no_port_number(tmp_path: Path, line: str) -> None:
    (tmp_path / ".env.example").write_text(line + "\n")
    assert _collect(tmp_path).claims == []


@pytest.mark.parametrize(
    "line",
    [
        "PATH=/usr/local/bin",
        "PYTHONPATH=/srv/lib",
        "JAVA_HOME=/opt/jdk",
        "SSL_CERT_FILE=/etc/ssl/cert.pem",
        "CONFIG_DIR=/etc/app",
        "DATA_DIR=relative/data",
        "DATA_DIR=/",
        "DATA_DIR=C:\\",
        "PUBLIC_URL=/static",
        "STORAGE_PATH=s3://bucket/uploads",
        "UPLOAD_DIR=${ROOT}/uploads",
    ],
)
def test_paths_that_are_not_shared_mutable_locations(tmp_path: Path, line: str) -> None:
    (tmp_path / ".env.example").write_text(line + "\n")
    assert _collect(tmp_path).claims == []


def test_windows_paths(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("UPLOAD_DIR=C:\\data\\uploads\\\n")
    assert {c.key for c in _collect(tmp_path).claims} == {"path://C:\\data\\uploads"}


def test_a_relative_sqlite_file_belongs_to_each_worktree(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "DATABASE_URL=sqlite:///data/app.db\nSHARED_DB=sqlite:////srv/app.db\n"
    )
    assert {c.key for c in _collect(tmp_path).claims} == {"db://sqlite//srv/app.db"}


def test_local_env_files_need_opt_in(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PORT=1111\n")
    (tmp_path / ".env.local").write_text("PORT=2222\n")
    left_out = _collect(tmp_path)
    assert left_out.claims == []
    assert [(s.source.path, s.reason) for s in left_out.skipped] == [
        (".env", "was not read: .env files are read only with --include-env"),
        (".env.local", "was not read: .env files are read only with --include-env"),
    ]
    opted_in = _collect(tmp_path, Policy(include_env_files=True))
    assert opted_in.skipped == []
    assert _claims(opted_in) == {
        ("listen_port", "tcp://*:1111", ".env", 1),
        ("listen_port", "tcp://*:2222", ".env.local", 1),
    }


def test_files_in_a_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / ".env.template").write_text("PORT=5173\n")
    out = _collect(tmp_path, directory="apps/web")
    assert _claims(out) == {("listen_port", "tcp://*:5173", "apps/web/.env.template", 1)}


def test_an_unreadable_database_url_is_recorded_without_its_value(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"DATABASE_URL=postgres://app:{CANARY}/x@db.internal/app\n"
        f"DB_PASSWORD={CANARY}\n"
        f"CACHE_URL=redis://:{CANARY}@cache:6379/1\n"
    )
    out = _collect(tmp_path, Policy(include_env_files=True))
    (unreadable,) = out.unreadable
    assert (unreadable.kind, unreadable.name, unreadable.source.line) == (
        ResourceKind.DATABASE,
        "DATABASE_URL",
        1,
    )
    assert _claims(out) == {("database", "db://redis/cache:6379/1", ".env", 3)}
    assert CANARY not in repr(out)


def test_a_file_over_the_cap_is_skipped_and_reported(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("PORT=1\n" + "#" * 200 + "\n")
    out = _collect(tmp_path, Policy(max_file_bytes=100))
    assert out.claims == []
    (skipped,) = out.skipped
    assert (skipped.source.path, skipped.reason) == (".env.example", "is larger than 100 bytes")


def test_details_say_what_was_read(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "HOST=127.0.0.1\nPORT=3000\nDATABASE_URL=postgres://u:p@localhost/app\nLOG_DIR=/var/log/app\n"
    )
    details = {c.key: c.detail for c in _collect(tmp_path).claims}
    assert details == {
        "tcp://127.0.0.1:3000": "PORT=3000 (HOST=127.0.0.1)",
        "db://postgres/localhost:5432/app": "DATABASE_URL",
        "path:///var/log/app": "LOG_DIR=/var/log/app",
    }


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("::1", "tcp://[::1]:3000"),
        ("[::1]", "tcp://[::1]:3000"),
        ("Dev-Box.local", "tcp://dev-box.local:3000"),
        ("not a host", "tcp://*:3000"),
        ("${BIND}", "tcp://*:3000"),
        ("bücher.example", "tcp://*:3000"),
    ],
)
def test_only_literal_hosts_narrow_a_port(tmp_path: Path, host: str, key: str) -> None:
    (tmp_path / ".env.example").write_text(f"HOST={host}\nPORT=3000\n", encoding="utf-8")
    assert {c.key for c in _collect(tmp_path).claims} == {key}
