"""Terminal report of ``scan``: what needs attention in full, everything else in a line.

Collected text is added as plain ``Text``. Findings that follow from another one
(``caused_by``) are shown under it rather than as separate problems.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import PurePosixPath

from rich.console import Console
from rich.table import Table
from rich.text import Text

from worktree_shield.collectors.envfiles import LOCAL_FILES
from worktree_shield.models import Finding, Snapshot, Status
from worktree_shield.plan import Suggestion
from worktree_shield.reports.terminal import (
    display_path,
    redaction_line,
    render_failed_discovery,
    worktree_names,
)
from worktree_shield.rules.common import VERIFY, VERIFY_WITH_ENV

PROBLEMS = (Status.FAIL, Status.WARN, Status.UNKNOWN)
LABEL = {
    Status.FAIL: "FAIL",
    Status.WARN: "WARN",
    Status.UNKNOWN: "UNKNOWN",
    Status.PASS: "PASS",
    Status.NOT_APPLICABLE: "N/A",
    Status.NOT_TESTED: "NOT TESTED",
}
_STYLE = {Status.FAIL: "bold red", Status.WARN: "bold yellow", Status.UNKNOWN: "bold magenta"}
_ORDER = {status: index for index, status in enumerate(PROBLEMS)}


def counts_line(findings: tuple[Finding, ...]) -> str:
    """``2 fail, 3 warn, 1 unknown, 6 pass, 1 not applicable``."""
    counts = Counter(f.status for f in findings)
    parts = [
        f"{counts[status]} {label}"
        for status, label in (
            (Status.FAIL, "fail"),
            (Status.WARN, "warn"),
            (Status.UNKNOWN, "unknown"),
            (Status.PASS, "pass"),
            (Status.NOT_APPLICABLE, "not applicable"),
            (Status.NOT_TESTED, "not tested"),
        )
        if counts[status]
    ]
    return ", ".join(parts) if parts else "no findings"


def render_scan(snapshot: Snapshot, console: Console, *, show_all: bool = False) -> None:
    """The scan report of an already redacted, diagnosed snapshot."""
    repository = snapshot.repository
    console.print(Text(f"worktree-shield {snapshot.tool_version}", style="bold"))
    if repository is None:
        render_failed_discovery(snapshot, console)
        return
    name, parent = worktree_names(repository)
    count = len(repository.worktrees)
    policy = snapshot.policy
    source = display_path(policy.source) if policy and policy.source else "built-in defaults"
    console.print(Text(f"{count} worktree{'s' if count != 1 else ''}, policy: {source}"))
    if parent is not None:
        console.print(Text(f"Worktrees are named relative to {display_path(parent)}", style="dim"))
    console.print(Text(counts_line(snapshot.findings), style="bold"))
    problems = [f for f in snapshot.findings if f.status in PROBLEMS and f.caused_by is None]
    problems.sort(key=lambda f: _ORDER[f.status])  # stable: catalog order within a status
    followers = [f for f in snapshot.findings if f.status in PROBLEMS and f.caused_by]
    for finding in problems:
        console.print()
        _render_problem(finding, name, console)
        for follower in followers:
            if follower.caused_by == finding.id:
                console.print(
                    Text(f"      Follows from it: {follower.id} {follower.summary}", style="dim")
                )
    orphans = [f for f in followers if f.caused_by not in {p.id for p in problems}]
    for finding in orphans:
        console.print()
        _render_problem(finding, name, console)
    rest = [f for f in snapshot.findings if f.status not in PROBLEMS]
    if rest and show_all:
        console.print()
        table = Table(box=None, show_edge=False, pad_edge=False, show_header=False)
        table.add_column("Status", no_wrap=True)
        table.add_column("Rule", no_wrap=True)
        table.add_column("Summary", overflow="fold")
        for finding in rest:
            table.add_row(Text(LABEL[finding.status]), Text(finding.id), Text(finding.summary))
        console.print(table)
    elif rest:
        console.print()
        console.print(
            Text(
                f"{len(rest)} more checks passed or did not apply (--all lists them).", style="dim"
            )
        )
    console.print()
    footer = "Read-only: nothing in the repository was run, changed or locked."
    line = redaction_line(snapshot)
    console.print(Text(footer + (f" {line}." if line else ""), style="dim"))


def _render_problem(finding: Finding, label: Callable[[str], str], console: Console) -> None:
    header = Text()
    header.append(f"{LABEL[finding.status]:<8}", style=_STYLE.get(finding.status, "bold"))
    header.append(f"{finding.id}  ", style="bold")
    header.append(finding.summary)
    if finding.certainty is not None:
        header.append(f"  ({finding.certainty.value})", style="dim")
    console.print(header)
    console.print(Text(f"        {finding.reason}"))
    if finding.evidence:
        table = Table(
            box=None, show_edge=False, pad_edge=False, show_header=False, padding=(0, 2, 0, 0)
        )
        table.add_column("indent", width=6)
        table.add_column("Worktree", no_wrap=True)
        table.add_column("Where", overflow="fold")
        table.add_column("What", overflow="fold")
        for item in finding.evidence:
            table.add_row(
                Text(""),
                Text(label(item.key)),
                Text(display_path(item.source)),
                Text(item.value or ""),
            )
        console.print(table)
    if finding.recommended_action:
        console.print(Text(f"        Next: {finding.recommended_action}"))
    if finding.verify_command:
        console.print(Text(f"        Check: {finding.verify_command}", style="dim"))
    for limitation in finding.limitations:
        console.print(Text(f"        Note: {limitation}", style="dim"))


def render_plan(snapshot: Snapshot, suggestions: list[Suggestion], console: Console) -> None:
    """The suggested changes, grouped by worktree; nothing is applied."""
    console.print(Text(f"worktree-shield {snapshot.tool_version}", style="bold"))
    if snapshot.repository is None:
        render_failed_discovery(snapshot, console)
        return
    if not suggestions:
        console.print(Text("Nothing to change: no collision needs attention."))
        return
    name, _ = worktree_names(snapshot.repository)
    in_env = any(PurePosixPath(s.where.split(":", 1)[0]).name in LOCAL_FILES for s in suggestions)
    reads_env = snapshot.policy is not None and snapshot.policy.include_env_files
    check = VERIFY_WITH_ENV if in_env and not reads_env else VERIFY
    console.print(
        Text(f"Suggested changes. Nothing was changed: make them yourself, then run {check}.")
    )
    by_worktree: dict[str, list[Suggestion]] = {}
    for suggestion in suggestions:
        by_worktree.setdefault(suggestion.worktree, []).append(suggestion)
    for worktree, items in by_worktree.items():
        console.print()
        console.print(Text(name(worktree), style="bold"))
        table = Table(box=None, show_edge=False, pad_edge=False, show_header=False)
        table.add_column("indent", width=2)
        table.add_column("Where", no_wrap=True)
        table.add_column("Change", overflow="fold")
        table.add_column("Rule", no_wrap=True, style="dim")
        for item in items:
            table.add_row(
                Text(""), Text(display_path(item.where)), Text(item.change), Text(item.rule)
            )
        console.print(table)
