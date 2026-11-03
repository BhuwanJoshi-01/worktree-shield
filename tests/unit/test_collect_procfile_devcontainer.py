"""Listen ports in Procfiles and dev containers (WTS-003)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from tests.fakes import read_fixture
from worktree_shield.models import Policy

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-003")

PROCFILE = """\
# processes for foreman / honcho
web: bundle exec rails server -p 3000
api: uvicorn api:app --port $PORT
worker: bundle exec sidekiq
css: bin/rails tailwindcss:watch
admin: node admin.js --port 4000   # a trailing comment
not a process line
"""


def _collect(root: Path) -> Any:
    from worktree_shield.collectors.base import Collected, Scope
    from worktree_shield.collectors.procfile import collect_devcontainer, collect_procfiles

    out = Collected()
    scope = Scope(root, "/repos/app", Policy().max_file_bytes)
    collect_procfiles(scope, PurePosixPath(), out)
    collect_devcontainer(scope, PurePosixPath(), out)
    return out


def _claims(out: Any) -> list[tuple[str, str, int | None, str, bool | None]]:
    return [(c.key, c.source.path, c.source.line, c.detail, c.strict) for c in out.claims]


def test_procfile_processes(tmp_path: Path) -> None:
    (tmp_path / "Procfile").write_text(PROCFILE, encoding="utf-8")
    (tmp_path / "Procfile.dev").write_text("web: bin/vite dev --port 3036\n", encoding="utf-8")
    assert _claims(_collect(tmp_path)) == [
        ("tcp://*:3000", "Procfile", 2, "Procfile web: -p 3000", None),
        ("tcp://*:4000", "Procfile", 6, "Procfile admin: --port 4000", None),
        ("tcp://*:3036", "Procfile.dev", 1, "Procfile.dev web: --port 3036", False),
    ]


def test_devcontainer_ports(tmp_path: Path) -> None:
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text(
        read_fixture("devcontainer", "devcontainer.json"), encoding="utf-8"
    )
    assert _claims(_collect(tmp_path)) == [
        ("tcp://localhost:3000", ".devcontainer/devcontainer.json", 7, "forwardPorts: 3000", False),
        (
            "tcp://localhost:5432",
            ".devcontainer/devcontainer.json",
            8,
            "forwardPorts: db:5432",
            False,
        ),
        ("tcp://*:8080", ".devcontainer/devcontainer.json", 10, "appPort: 8080:80", True),
        ("tcp://*:9229", ".devcontainer/devcontainer.json", 10, "appPort: 9229", True),
    ]


def test_a_devcontainer_file_at_the_root(tmp_path: Path) -> None:
    (tmp_path / ".devcontainer.json").write_text('{"appPort": 8000}', encoding="utf-8")
    assert [c.key for c in _collect(tmp_path).claims] == ["tcp://*:8000"]


@pytest.mark.parametrize(
    "text",
    ['{"forwardPorts": "3000"}', '{"appPort": [true]}', '{"forwardPorts": [70000, "x:y"]}', "[]"],
)
def test_odd_values_yield_nothing(tmp_path: Path, text: str) -> None:
    (tmp_path / ".devcontainer.json").write_text(text, encoding="utf-8")
    out = _collect(tmp_path)
    assert out.claims == []
    assert out.skipped == []


def test_invalid_json_is_skipped(tmp_path: Path) -> None:
    (tmp_path / ".devcontainer.json").write_text('{"appPort": [8000,, ]}', encoding="utf-8")
    (skipped,) = _collect(tmp_path).skipped
    assert skipped.reason == "is not valid JSON"


def test_jsonc_comments_and_trailing_commas() -> None:
    import json

    from worktree_shield.parsers.jsonc import strip_jsonc

    text = '{\n  // a\n  "a": "b // c", /* d\n */ "e": [1, 2,],\n}'
    stripped = strip_jsonc(text)
    assert json.loads(stripped) == {"a": "b // c", "e": [1, 2]}
    assert stripped.count("\n") == text.count("\n")  # lines stay where they were
