"""Literal listen ports in script command lines, read as text (WTS-003)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-003")


def _ports(command: str) -> list[tuple[int, str | None, str, bool | None]]:
    from worktree_shield.parsers.commands import listen_ports

    return [(m.port, m.host, m.fragment, m.strict) for m in listen_ports(command)]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("vite --port 5173", [(5173, None, "--port 5173", False)]),
        ("vite --port=5174 --strictPort", [(5174, None, "--port=5174", True)]),
        ("vite --host 127.0.0.1 --port 5173", [(5173, "127.0.0.1", "--port 5173", False)]),
        ("next dev -p 3001", [(3001, None, "-p 3001", None)]),
        ("serve -l 5000 dist", [(5000, None, "-l 5000", None)]),
        ("PORT=4000 node server.js", [(4000, None, "PORT=4000", None)]),
        ("cross-env API_PORT=8081 nodemon api.js", [(8081, None, "API_PORT=8081", None)]),
        ("uvicorn app.main:app --reload --port 8000", [(8000, None, "--port 8000", None)]),
        ("uvicorn app:app --host 0.0.0.0 --port 8000", [(8000, "0.0.0.0", "--port 8000", None)]),
        ("gunicorn -b 127.0.0.1:8001 app:app", [(8001, "127.0.0.1", "-b 127.0.0.1:8001", None)]),
        ("gunicorn --bind=:8002 app:app", [(8002, None, "--bind=:8002", None)]),
        ("python manage.py runserver 8003", [(8003, None, "runserver 8003", None)]),
        (
            "python manage.py runserver 0.0.0.0:8004",
            [(8004, "0.0.0.0", "runserver 0.0.0.0:8004", None)],
        ),
        ("python -m http.server 8005", [(8005, None, "http.server 8005", None)]),
        ("php -S localhost:8006 -t public", [(8006, "localhost", "-S localhost:8006", None)]),
        (
            "concurrently 'vite --port 5173' 'PORT=3000 node api.js'",
            [(5173, None, "--port 5173", False), (3000, None, "PORT=3000", None)],
        ),
        (
            "npm run build && vite preview --port 4173 --strictPort",
            [(4173, None, "--port 4173", True)],
        ),
    ],
)
def test_listen_ports(command: str, expected: list[Any]) -> None:
    assert _ports(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "tsc -p tsconfig.json",
        "mkdir -p dist",
        "docker run -p 8080:80 nginx",
        "psql -p 5432 app",
        "redis-cli -p 6379 ping",
        "ssh -p 2222 deploy@host",
        "vite --port $PORT",
        "vite --port ${VITE_PORT:-5173}",
        "vite --port 70000",
        "DB_PORT=5432 node migrate.js",
        "echo 'unbalanced",
        "",
    ],
)
def test_no_listen_port(command: str) -> None:
    assert _ports(command) == []


@given(st.text(max_size=300))
def test_any_command_is_scanned_without_errors(command: str) -> None:
    from worktree_shield.parsers.commands import listen_ports

    for mention in listen_ports(command):
        assert 1 <= mention.port <= 65535
