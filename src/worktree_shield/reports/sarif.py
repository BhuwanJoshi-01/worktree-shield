"""SARIF 2.1.0 output, for code scanning (GitHub and other SARIF viewers).

Only findings that need attention and point to a file become results: fail is
``error``, warn ``warning``, unknown ``note``. Locations are the claims of the current
worktree, relative to it, so a viewer of that checkout opens the right line; claims of
other worktrees become related locations whose message names the worktree. Each result
has a fingerprint from its rule and resource, stable across runs, so a viewer can tell
a new collision from one it has seen. Pass a redacted snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from worktree_shield.models import Finding, Snapshot, SourceRef, Status
from worktree_shield.reports.markdown import PROJECT_URL
from worktree_shield.rules.catalog import builtin_rules

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_LEVEL = {Status.FAIL: "error", Status.WARN: "warning", Status.UNKNOWN: "note"}


def _anchor(rule_id: str, title: str) -> str:
    """The GitHub anchor of the rule's heading in docs/rules.md."""
    heading = f"{rule_id}: {title}".lower()
    return re.sub(r"[^a-z0-9 -]", "", heading).replace(" ", "-")


def render_sarif(snapshot: Snapshot) -> str:
    """One SARIF run with every rule and a result per located problem."""
    rules = builtin_rules()
    index = {rule.id: i for i, rule in enumerate(rules)}
    current = snapshot.repository.current if snapshot.repository else None
    results = [
        result
        for finding in snapshot.findings
        if finding.status in _LEVEL and finding.sources
        for result in [_result(finding, index[finding.id], current)]
    ]
    document: dict[str, Any] = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "worktree-shield",
                        "version": snapshot.tool_version,
                        "semanticVersion": snapshot.tool_version,
                        "informationUri": PROJECT_URL,
                        "rules": [
                            {
                                "id": rule.id,
                                "name": rule.id.replace("-", ""),
                                "shortDescription": {"text": rule.title},
                                "helpUri": f"{PROJECT_URL}/blob/main/docs/rules.md#"
                                + _anchor(rule.id, rule.title),
                            }
                            for rule in rules
                        ],
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _location(source: SourceRef, message: str | None = None) -> dict[str, Any]:
    physical: dict[str, Any] = {"artifactLocation": {"uri": source.path}}
    if source.line is not None:
        physical["region"] = {"startLine": source.line}
    location: dict[str, Any] = {"physicalLocation": physical}
    if message:
        location["message"] = {"text": message}
    return location


def _message(finding: Finding) -> str:
    """Summary, reason and next step: SARIF fixes need file edits, so advice goes here."""
    parts = [f"{finding.summary}.", finding.reason]
    if finding.recommended_action:
        parts.append(f"Next: {finding.recommended_action}")
    return " ".join(parts)


def _result(finding: Finding, rule_index: int, current: str | None) -> dict[str, Any]:
    files = [s for s in finding.sources if not s.path.startswith("pid ")]
    here = [s for s in files if s.worktree == current] or files[:1]
    elsewhere = [s for s in files if s not in here]
    result: dict[str, Any] = {
        "ruleId": finding.id,
        "ruleIndex": rule_index,
        "level": _LEVEL[finding.status],
        "message": {"text": _message(finding)},
        "locations": [_location(s) for s in here],
        "partialFingerprints": {
            "worktreeShield/v1": hashlib.sha256(
                f"{finding.id}\0{finding.resource_key or finding.summary}".encode()
            ).hexdigest()
        },
        "properties": {
            "certainty": finding.certainty.value if finding.certainty else None,
            "worktrees": list(finding.worktrees),
        },
    }
    if elsewhere:
        result["relatedLocations"] = [
            {"id": i, **_location(s, f"in the worktree {s.worktree}")}
            for i, s in enumerate(elsewhere)
        ]
    return result
