"""Markdown output: an issue- or PR-ready report of an already redacted snapshot.

Collected text is escaped, so a path containing ``|`` cannot break a table and
``<tag>`` cannot become HTML in an issue tracker; values go in code spans whose fence is
longer than any backtick run inside them.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from worktree_shield.models import Finding, Snapshot
from worktree_shield.reports.findings import LABEL, PROBLEMS, counts_line
from worktree_shield.reports.terminal import redaction_line, worktree_names

PROJECT_URL = "https://github.com/BhuwanJoshi-01/worktree-shield"
_SPECIAL = re.compile(r"([\\`*_\[\]<>|#])")


def text(value: str) -> str:
    """Plain text that Markdown and HTML will not interpret; one line."""
    return _SPECIAL.sub(r"\\\1", " ".join(value.split()))


def code(value: str) -> str:
    """An inline code span that survives any backticks inside the value."""
    flat = " ".join(value.split())
    longest = max((len(run) for run in re.findall(r"`+", flat)), default=0)
    fence = "`" * (longest + 1)
    padding = " " if flat.startswith("`") or flat.endswith("`") else ""
    return f"{fence}{padding}{flat}{padding}{fence}"


def cell_code(value: str) -> str:
    """A code span for a table cell: GitHub splits cells at ``|`` even inside code spans
    unless it is escaped."""
    return code(value).replace("|", "\\|")


def render_markdown(snapshot: Snapshot) -> str:
    """The report: counts, a table of every finding, then what needs attention."""
    lines = ["# Worktree collision report", ""]
    repository = snapshot.repository
    if repository is None:
        lines += ["The worktrees could not be listed:", ""]
        lines += [f"- {code(f.probe)}: {text(f.detail)}" for f in snapshot.probe_failures]
        return "\n".join([*lines, "", _footer(snapshot), ""])
    name, _ = worktree_names(repository)
    policy = snapshot.policy
    source = code(policy.source) if policy and policy.source else "built-in defaults"
    count = len(repository.worktrees)
    lines += [
        f"**{text(counts_line(snapshot.findings))}** across {count} "
        f"worktree{'s' if count != 1 else ''}. Policy: {source}.",
        "",
        f"worktree-shield {text(snapshot.tool_version)}, {text(snapshot.created_at)}.",
        "",
    ]
    if snapshot.findings:
        lines += ["| Status | Rule | Finding | Certainty |", "| --- | --- | --- | --- |"]
        for finding in snapshot.findings:
            certainty = finding.certainty.value if finding.certainty else "—"
            lines.append(
                f"| {LABEL[finding.status]} | {code(finding.id)} | {text(finding.summary)} "
                f"| {certainty} |"
            )
        lines.append("")
    problems = [f for f in snapshot.findings if f.status in PROBLEMS]
    if problems:
        lines += ["## What needs attention", ""]
        for finding in problems:
            lines += _details(finding, name)
    return "\n".join([*lines, _footer(snapshot), ""])


def _details(finding: Finding, label: Callable[[str], str]) -> list[str]:
    title = f"### {LABEL[finding.status]} {code(finding.id)}: {text(finding.summary)}"
    lines = [title, "", text(finding.reason), ""]
    if finding.caused_by:
        lines += [f"Follows from {code(finding.caused_by)}.", ""]
    if finding.evidence:
        lines += ["| Worktree | Where | What |", "| --- | --- | --- |"]
        for item in finding.evidence:
            value = cell_code(item.value) if item.value is not None else "not reported"
            lines.append(f"| {text(label(item.key))} | {cell_code(item.source)} | {value} |")
        lines.append("")
    if finding.recommended_action:
        lines += [f"**Next step:** {text(finding.recommended_action)}", ""]
    if finding.verify_command:
        lines += [f"**Check afterwards:** {code(finding.verify_command)}", ""]
    for limitation in finding.limitations:
        lines += [f"*Note:* {text(limitation)}", ""]
    return lines


def _footer(snapshot: Snapshot) -> str:
    closing = (
        f"---\n\nMade by [worktree-shield]({PROJECT_URL}), read-only: nothing in the "
        "repository was run, changed or locked."
    )
    line = redaction_line(snapshot)
    return closing + (f" {text(line)}." if line else "")
