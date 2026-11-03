"""Ports and paths in vite.config.*, matched as text and never executed (WTS-003, WTS-006)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from tests.fakes import read_fixture
from worktree_shield.models import Policy


def _collect(root: Path) -> Any:
    from worktree_shield.collectors.base import Collected, Scope
    from worktree_shield.collectors.vite import collect_vite_config

    out = Collected()
    collect_vite_config(Scope(root, "/repos/web", Policy().max_file_bytes), PurePosixPath(), out)
    return out


def _claims(out: Any) -> list[tuple[str, str, int | None, str, bool | None]]:
    return [(c.kind.value, c.key, c.source.line, c.detail, c.strict) for c in out.claims]


def test_the_example_config(tmp_path: Path) -> None:
    (tmp_path / "vite.config.ts").write_text(read_fixture("vite", "vite.config.ts"))
    assert _claims(_collect(tmp_path)) == [
        ("listen_port", "tcp://127.0.0.1:5173", 13, "server.port: 5173", True),
        ("listen_port", "tcp://*:4173", 21, "preview.port: 4173", False),
        (
            "absolute_path",
            "path:///tmp/vite-cache-shared",
            10,
            "cacheDir: /tmp/vite-cache-shared",
            None,
        ),
        ("absolute_path", "path:///srv/www/app", 24, "build.outDir: /srv/www/app", None),
    ]


@pytest.mark.parametrize(
    "name", ["vite.config.js", "vite.config.mjs", "vite.config.mts", "vite.config.cjs"]
)
def test_every_config_file_name(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("export default { server: { port: 3000 } }\n")
    assert [c.source.path for c in _collect(tmp_path).claims] == [name]


@pytest.mark.parametrize(
    "text",
    [
        "export default { server: { port: Number(process.env.PORT) } }",
        "export default { server: { port: env.PORT ?? 5173 } }",
        "export default { server: { hmr: { port: 24678 } } }",
        "export default { server: { port: 70000 } }",
        "// server: { port: 3000 }",
        "const s = 'server: { port: 3000 }'",
        "export default { build: { outDir: 'dist' } }",
        "export default { build: { sourcemap: true } }",
        "export default { build: { outDir: '/srv/' + name } }",
        "export default { server: { port: 3000 ",  # never closed
    ],
)
def test_nothing_that_is_not_a_literal_setting(tmp_path: Path, text: str) -> None:
    (tmp_path / "vite.config.js").write_text(text + "\n")
    assert _collect(tmp_path).claims == []


def test_strict_port_false_and_a_wildcard_host(tmp_path: Path) -> None:
    (tmp_path / "vite.config.js").write_text(
        "export default {\n  server: { host: true, port: 3000, strictPort: false },\n}\n"
    )
    assert _claims(_collect(tmp_path)) == [
        ("listen_port", "tcp://*:3000", 2, "server.port: 3000", False)
    ]


def test_template_literals_and_regexes_do_not_confuse_it(tmp_path: Path) -> None:
    (tmp_path / "vite.config.js").write_text(
        "const a = `server: { port: 1 } ${'}'}`\n"
        "const b = /\\{/\n"
        "export default { server: { port: 3001 } }\n"
    )
    assert [c.key for c in _collect(tmp_path).claims] == ["tcp://*:3001"]
