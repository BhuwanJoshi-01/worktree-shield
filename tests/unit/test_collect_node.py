"""Listen ports in package.json scripts (WTS-003)."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from worktree_shield.models import Policy

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-003")

PACKAGE = """{
  "name": "web",
  "scripts": {
    "dev": "vite --port 5173",
    "preview": "vite preview --port 4173 --strictPort",
    "api": "PORT=3000 node server.js",
    "db": "psql -p 5432 app",
    "build": "tsc -p tsconfig.json && vite build"
  },
  "config": {
    "port": "8080"
  }
}
"""


def _collect(root: Path, directory: str = "") -> Any:
    from worktree_shield.collectors.base import Collected, Scope
    from worktree_shield.collectors.node import collect_package_json

    out = Collected()
    collect_package_json(
        Scope(root, "/repos/web", Policy().max_file_bytes), PurePosixPath(directory), out
    )
    return out


def test_scripts_and_config_port(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(PACKAGE)
    claims = [
        (c.kind.value, c.key, c.source.path, c.source.line, c.detail, c.strict)
        for c in _collect(tmp_path).claims
    ]
    assert claims == [
        ("listen_port", "tcp://*:5173", "package.json", 4, "scripts.dev: --port 5173", False),
        ("listen_port", "tcp://*:4173", "package.json", 5, "scripts.preview: --port 4173", True),
        ("listen_port", "tcp://*:3000", "package.json", 6, "scripts.api: PORT=3000", None),
        ("listen_port", "tcp://*:8080", "package.json", 11, "config.port=8080", None),
    ]


def test_a_host_in_the_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"dev": "next dev -H 127.0.0.1 -p 3001"}})
    )
    assert [c.key for c in _collect(tmp_path).claims] == ["tcp://127.0.0.1:3001"]


def test_a_package_in_a_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "package.json").write_text(PACKAGE)
    paths = {c.source.path for c in _collect(tmp_path, "apps/web").claims}
    assert paths == {"apps/web/package.json"}


def test_only_the_fragment_naming_the_port_is_kept(tmp_path: Path) -> None:
    canary = "sk-canary-0042"
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": f"API_KEY={canary} node api.js --port 3000"}})
    )
    out = _collect(tmp_path)
    assert [c.detail for c in out.claims] == ["scripts.start: --port 3000"]
    assert canary not in repr(out)


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        '{"scripts": ["vite --port 1"]}',
        '{"scripts": {"dev": 5173}}',
        '{"config": {"port": "not a port"}}',
        '{"config": "port=1"}',
    ],
)
def test_unexpected_shapes_yield_nothing(tmp_path: Path, text: str) -> None:
    (tmp_path / "package.json").write_text(text)
    out = _collect(tmp_path)
    assert out.claims == []
    assert out.skipped == []


def test_invalid_json_is_reported_as_skipped(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{\n  "scripts": {,}\n}\n')
    (skipped,) = _collect(tmp_path).skipped
    assert (skipped.source.path, skipped.source.line) == ("package.json", 2)
    assert skipped.reason == "is not valid JSON"


def test_script_names_with_unicode_and_escapes(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{\n"scripts": {\n"d\\u00e9mo": "vite --port 1",\n"démo:2": "vite --port 2"\n}\n}\n',
        encoding="utf-8",
    )
    lines = [(c.detail, c.source.line) for c in _collect(tmp_path).claims]
    assert lines == [("scripts.démo: --port 1", 3), ("scripts.démo:2: --port 2", 4)]


def test_no_package_json(tmp_path: Path) -> None:
    out = _collect(tmp_path)
    assert (out.claims, out.skipped) == ([], [])
