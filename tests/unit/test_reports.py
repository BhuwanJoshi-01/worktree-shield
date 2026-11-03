"""Markdown and SARIF output, and the report command (WTS-009)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from worktree_shield.models import (
    Confidence,
    Evidence,
    FailureKind,
    Finding,
    ProbeFailure,
    Repository,
    Severity,
    Snapshot,
    SourceRef,
    Status,
    Worktree,
)
from worktree_shield.reports.markdown import cell_code, code, render_markdown, text
from worktree_shield.reports.sarif import render_sarif

A, B = "/src/app", "/src/app-login"
REPOSITORY = Repository("/src/app/.git", A, False, (Worktree(A), Worktree(B)))


def finding(status: Status = Status.FAIL, **extra: object) -> Finding:
    values: dict[str, object] = {
        "resource_key": "tcp://*:5173",
        "worktrees": (A, B),
        "sources": (SourceRef(A, ".env.example", 1), SourceRef(B, "vite.config.ts", 4)),
        "evidence": (
            Evidence(".env.example:1", A, "PORT=5173"),
            Evidence("vite.config.ts:4", B, None),
        ),
        "recommended_action": "Give each worktree its own port.",
        "verify_command": "worktree-shield scan --strict",
        "limitations": ("Only when both run.",),
    }
    values.update(extra)
    return Finding(
        "WTS-PORT-001",
        status,
        Severity.HIGH,
        Confidence.MEDIUM,
        "Port 5173 is configured in 2 worktrees",
        "Only one can listen.",
        **values,  # type: ignore[arg-type]
    )


def snapshot(*findings: Finding) -> Snapshot:
    return Snapshot("0.1.0", "2026-11-04T10:00:00Z", repository=REPOSITORY, findings=findings)


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("a|b", "a\\|b"),
        ("<b>x</b>", "\\<b\\>x\\</b\\>"),
        ("*x* _y_", "\\*x\\* \\_y\\_"),
        ("a\nb", "a b"),
    ],
)
def test_text_is_escaped(raw: str, escaped: str) -> None:
    assert text(raw) == escaped


def test_code_spans_survive_backticks_and_pipes() -> None:
    assert code("a`b") == "``a`b``"
    assert code("`x`") == "`` `x` ``"
    assert cell_code("a|b") == "`a\\|b`"


def test_markdown_lists_every_finding_and_details_the_problems() -> None:
    passed = Finding(
        "WTS-GIT-002",
        Status.PASS,
        Severity.INFO,
        Confidence.HIGH,
        "Every listed worktree exists",
        "ok",
    )
    follower = finding(Status.WARN, caused_by="WTS-DOCKER-001")
    out = render_markdown(snapshot(finding(), passed, follower))
    assert out.startswith("# Worktree collision report\n")
    assert "**1 fail, 1 warn, 1 pass** across 2 worktrees. Policy: built-in defaults." in out
    assert "| FAIL | `WTS-PORT-001` | Port 5173 is configured in 2 worktrees | — |" in out
    assert "### FAIL `WTS-PORT-001`: Port 5173 is configured in 2 worktrees" in out
    assert "| app | `.env.example:1` | `PORT=5173` |" in out
    assert "| app-login | `vite.config.ts:4` | not reported |" in out
    assert "**Next step:** Give each worktree its own port." in out
    assert "**Check afterwards:** `worktree-shield scan --strict`" in out
    assert "Follows from `WTS-DOCKER-001`." in out
    assert "### PASS" not in out
    assert out.rstrip().endswith("nothing in the repository was run, changed or locked.")


def test_markdown_of_a_failed_discovery() -> None:
    failure = ProbeFailure("git worktree list", FailureKind.TIMEOUT, "git did not finish")
    out = render_markdown(Snapshot("0.1.0", "t", probe_failures=(failure,)))
    assert "- `git worktree list`: git did not finish" in out


def test_sarif_results_locations_and_fingerprints() -> None:
    unknown = Finding(
        "WTS-RUNTIME-001", Status.UNKNOWN, Severity.LOW, Confidence.MEDIUM, "View limited", "why"
    )
    runtime = finding(
        Status.WARN, sources=(SourceRef(B, "pid 7"), SourceRef(A, ".env.example", 1)), evidence=()
    )
    document = json.loads(render_sarif(snapshot(finding(), unknown, runtime)))
    run = document["runs"][0]
    assert document["version"] == "2.1.0"
    rules = run["tool"]["driver"]["rules"]
    assert rules[0]["id"] == "WTS-PORT-001"
    first, second = run["results"]  # the finding without a file is left out
    assert (first["ruleId"], first["level"], first["ruleIndex"]) == ("WTS-PORT-001", "error", 0)
    assert first["locations"] == [
        {
            "physicalLocation": {
                "artifactLocation": {"uri": ".env.example"},
                "region": {"startLine": 1},
            }
        }
    ]
    assert first["relatedLocations"][0]["message"]["text"] == f"in the worktree {B}"
    assert "Next: Give each worktree its own port." in first["message"]["text"]
    assert second["level"] == "warning"
    assert [loc["physicalLocation"]["artifactLocation"]["uri"] for loc in second["locations"]] == [
        ".env.example"
    ]  # a pid is no file
    again = json.loads(render_sarif(snapshot(finding())))["runs"][0]["results"][0]
    assert again["partialFingerprints"] == first["partialFingerprints"]


def test_sarif_help_links_point_at_real_headings() -> None:
    rules_doc = (Path(__file__).parents[2] / "docs" / "rules.md").read_text(encoding="utf-8")
    anchors = {
        re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
        for heading in re.findall(r"^## (.+)$", rules_doc, re.M)
    }
    document = json.loads(render_sarif(snapshot()))
    for rule in document["runs"][0]["tool"]["driver"]["rules"]:
        assert rule["helpUri"].rsplit("#", 1)[1] in anchors
