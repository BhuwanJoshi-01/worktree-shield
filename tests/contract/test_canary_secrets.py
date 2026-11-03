"""Planted secrets reach no output format, nor do home paths (WTS-010)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from tests.gitrepos import add_worktree, git, make_repo
from worktree_shield.orchestrator import diagnose, inspect_resources
from worktree_shield.privacy import RedactionContext, redact_snapshot
from worktree_shield.reports.findings import render_scan
from worktree_shield.reports.json_report import render_json
from worktree_shield.reports.markdown import render_markdown
from worktree_shield.reports.sarif import render_sarif
from worktree_shield.reports.terminal import render_resources
from worktree_shield.runner import SubprocessRunner

CANARIES = ("Canary-Pass-31", "sk-canary-0000000000000000000000000000", "canary_token_77")


def _terminal(render: object, snapshot: object) -> str:
    console = Console(width=300, color_system=None)
    with console.capture() as capture:
        render(snapshot, console)  # type: ignore[operator]
    return capture.get()


@pytest.fixture
def outputs(tmp_path: Path) -> list[str]:
    home = tmp_path / "home" / "alice"
    main = make_repo(home, "shop")
    (main / ".env.example").write_text("PORT=5173\n", encoding="utf-8")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "env")
    login = add_worktree(main, home / "shop-login", "login")
    for worktree in (main, login):
        (worktree / ".env").write_text(
            f"DB_PASSWORD={CANARIES[0]}\n"
            f"OPENAI_API_KEY={CANARIES[1]}\n"
            f"DATABASE_URL=postgres://alice:{CANARIES[0]}@localhost:5432/shop_dev\n"
            f"BROKEN_URL=postgres://alice:{CANARIES[2]}/x@db/shop\n"
            f"UPLOAD_DIR={home}/uploads\n",
            encoding="utf-8",
        )
    snapshot = diagnose(inspect_resources(SubprocessRunner(), main, include_env_files=True))
    redacted = redact_snapshot(snapshot, RedactionContext(home=str(home), user="alice"))
    return [
        render_json(redacted),
        render_markdown(redacted),
        render_sarif(redacted),
        _terminal(render_scan, redacted),
        _terminal(render_resources, redacted),
    ]


def test_no_secret_reaches_any_output(outputs: list[str]) -> None:
    for output in outputs:
        for canary in CANARIES:
            assert canary not in output


def test_the_home_directory_is_hidden_everywhere(outputs: list[str], tmp_path: Path) -> None:
    home = str(tmp_path / "home" / "alice")
    for output in outputs:
        assert home not in output
        assert home not in json.dumps(output)  # escaped in JSON strings as well
    assert any("~/uploads" in output for output in outputs)
