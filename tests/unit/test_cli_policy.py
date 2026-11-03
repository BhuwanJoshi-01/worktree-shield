"""`worktree-shield policy` (WTS-002)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.gitrepos import add_worktree, git, make_repo, tree_digest
from worktree_shield import cli
from worktree_shield.config import POLICY_FILE
from worktree_shield.privacy import strip_control


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["worktree-shield", *args])
    monkeypatch.setenv("COLUMNS", "300")  # long temporary paths on one line
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    code = exit_info.value.code
    return code if isinstance(code, int) else 0


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(strip_control(capsys.readouterr().out).split())


def test_without_a_policy_file_the_defaults_apply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path)
    assert _run(monkeypatch, "policy", "--repo", str(main)) == 0
    out = _out(capsys)
    assert "Built-in defaults" in out
    assert "No .worktree-shield.toml in" in out
    assert "policy.shared_host_ports deny" in out
    assert "allow.ports none" in out
    assert "default:" not in out


def test_values_from_the_file_show_the_default_they_replace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path)
    (main / POLICY_FILE).write_text(
        "schema_version = 1\n[policy]\nshared_database = 'deny'\n[allow]\nports = [5432]\n"
    )
    assert _run(monkeypatch, "policy", "--repo", str(main)) == 0
    out = _out(capsys)
    assert f"Policy from {main / POLICY_FILE}" in out
    assert "policy.shared_database deny default: warn" in out
    assert "allow.ports 5432 default: none" in out
    # a value the file leaves alone has no note
    assert "policy.shared_host_ports deny policy.shared_database" in out


def test_each_worktree_has_its_own_policy_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path)
    (main / POLICY_FILE).write_text("schema_version = 1\n[policy]\nshared_database = 'deny'\n")
    linked = add_worktree(main, tmp_path / "linked", "feature")
    assert _run(monkeypatch, "policy", "--repo", str(linked)) == 0
    assert "Built-in defaults" in _out(capsys)  # the file is untracked in the main worktree


def test_a_bare_repository_has_the_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path)
    git(tmp_path, "clone", "-q", "--bare", str(main), str(tmp_path / "bare.git"))
    assert _run(monkeypatch, "policy", "--repo", str(tmp_path / "bare.git")) == 0
    assert "a bare repository has no policy file" in _out(capsys)


def test_a_broken_policy_file_exits_2_and_names_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path)
    (main / POLICY_FILE).write_text("schema_version = 1\n[policy]\nshared_ports = 'deny'\n")
    assert _run(monkeypatch, "policy", "--repo", str(main)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown key policy.shared_ports" in captured.err


def test_outside_a_repository_exits_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert _run(monkeypatch, "policy", "--repo", str(tmp_path)) == 3
    assert "is not inside a Git repository" in capsys.readouterr().err


def test_showing_the_policy_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    main = make_repo(tmp_path)
    (main / POLICY_FILE).write_text("schema_version = 1\n")
    before = tree_digest(main)
    assert _run(monkeypatch, "policy", "--repo", str(main)) == 0
    assert tree_digest(main) == before
