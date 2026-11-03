"""`worktree-shield explain` and `worktree-shield rules`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from worktree_shield import cli
from worktree_shield.rules.catalog import builtin_rules
from worktree_shield.rules.explain import rules_text

DOCS = Path(__file__).parents[2] / "docs" / "rules.md"


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["worktree-shield", *args])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    code = exit_info.value.code
    return code if isinstance(code, int) else 0


def test_the_packaged_rules_are_the_documented_ones() -> None:
    assert rules_text() == DOCS.read_text(encoding="utf-8")


def test_explain_prints_the_section_of_one_rule(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, "explain", "wts-port-002") == 0
    out = capsys.readouterr().out
    assert out.startswith("## WTS-PORT-002: A configured port already held by a running process")
    assert "WTS-DB-001" not in out


def test_the_last_rule_is_explained_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, "explain", "WTS-POLICY-001") == 0
    assert "never lets two servers listen on one port" in capsys.readouterr().out


def test_an_unknown_rule(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, "explain", "WTS-NOPE-001") == 2
    assert "worktree-shield rules lists them" in capsys.readouterr().err


def test_rules_lists_every_rule(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, "rules") == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == [rule.id for rule in builtin_rules()]
