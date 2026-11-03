"""The report command and scan --format (WTS-009)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.gitrepos import add_worktree, git, make_repo
from worktree_shield import cli


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["worktree-shield", *args])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    code = exit_info.value.code
    return code if isinstance(code, int) else 0


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    main = make_repo(tmp_path, "app")
    (main / ".env.example").write_text("PORT=5173\n", encoding="utf-8")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "env")
    add_worktree(main, tmp_path / "app-login", "login")
    return main


def test_report_writes_a_file_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], repo: Path, tmp_path: Path
) -> None:
    target = tmp_path / "out" / "report.md"
    target.parent.mkdir()
    assert (
        _run(monkeypatch, "report", "--repo", str(repo), "--scope", "static", "-o", str(target))
        == 0
    )
    assert target.read_text(encoding="utf-8").startswith("# Worktree collision report")
    assert "Wrote" in capsys.readouterr().err
    assert _run(monkeypatch, "report", "--repo", str(repo), "-o", str(target)) == 2
    assert "exists; use --force" in capsys.readouterr().err
    assert (
        _run(
            monkeypatch,
            "report",
            "--repo",
            str(repo),
            "-f",
            "sarif",
            "-o",
            str(target),
            "--force",
            "--strict",
            "--scope",
            "static",
        )
        == 1
    )
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == "2.1.0"


def test_scan_prints_json_for_scripts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], repo: Path
) -> None:
    assert (
        _run(monkeypatch, "scan", "--repo", str(repo), "--format", "json", "--scope", "static") == 0
    )
    document = json.loads(capsys.readouterr().out)
    assert document["summary"]["strict_failure"] is True
    assert (
        _run(
            monkeypatch, "report", "--repo", str(repo), "-f", "json", "-o", "-", "--scope", "static"
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
    assert (
        _run(monkeypatch, "scan", "--repo", str(repo), "--format", "markdown", "--scope", "static")
        == 0
    )
    assert capsys.readouterr().out.startswith("# Worktree collision report")
