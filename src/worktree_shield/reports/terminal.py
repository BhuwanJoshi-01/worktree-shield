"""Terminal output of an already redacted snapshot.

Collected text (paths, branch names, lock reasons) is added as plain ``Text``, never as
Rich markup, so a branch called ``[bold]x`` is printed as it is.
"""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from worktree_shield.models import Repository, Snapshot, Worktree

_REDACTION_NAMES = {
    "home_path": ("home path", "home paths"),
    "user_name": ("user name", "user names"),
    "host_name": ("host name", "host names"),
    "secret_value": ("secret value", "secret values"),
    "url_credentials": ("URL credential", "URL credentials"),
    "token": ("token", "tokens"),
}


def redaction_line(snapshot: Snapshot) -> str | None:
    """'Redacted from this output: 3 home paths, 1 secret value', or None if nothing was."""
    if not snapshot.redactions:
        return None
    parts = []
    for item in snapshot.redactions:
        singular, plural = _REDACTION_NAMES.get(item.kind, (item.kind, item.kind))
        parts.append(f"{item.count} {singular if item.count == 1 else plural}")
    return "Redacted from this output: " + ", ".join(parts)


def display_path(path: str) -> str:
    """A path on one line: newlines, tabs and other control characters shown escaped."""
    out = []
    for char in path:
        if char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 32 or ord(char) == 127:
            out.append(f"\\x{ord(char):02x}")
        else:
            out.append(char)
    return "".join(out)


def common_parent(paths: list[str]) -> str | None:
    """The directory all worktrees live in, if they share one below the root."""
    try:
        parent = os.path.commonpath(paths)
    except ValueError:  # different drives on Windows
        return None
    if parent in paths:  # one worktree contains the others: use its parent
        parent = str(Path(parent).parent)
    return parent if parent not in {"", ".", "/", os.sep} else None


def _ref(worktree: Worktree) -> str:
    if worktree.bare:
        return "bare repository"
    if worktree.branch:
        return worktree.branch.removeprefix("refs/heads/")
    if worktree.head:
        return f"detached at {worktree.head[:7]}"
    return "no commit"


def _notes(worktree: Worktree) -> str:
    notes = []
    if worktree.locked is not None:
        notes.append(f"locked: {worktree.locked}" if worktree.locked else "locked")
    if worktree.prunable is not None:
        notes.append(f"prunable: {worktree.prunable}" if worktree.prunable else "prunable")
    return "; ".join(notes)


def render_worktrees(snapshot: Snapshot, console: Console) -> None:
    """Every worktree of the repository, the current one marked."""
    repository: Repository | None = snapshot.repository
    console.print(Text(f"worktree-shield {snapshot.tool_version}", style="bold"))
    if repository is None:
        console.print(Text("The worktrees could not be listed:"))
        for failure in snapshot.probe_failures:
            console.print(Text(f"  {failure.probe}: {failure.detail}"))
        return
    count = len(repository.worktrees)
    plural = "s" if count != 1 else ""
    console.print(Text(f"{count} worktree{plural} sharing {display_path(repository.common_dir)}"))
    parent = common_parent([w.path for w in repository.worktrees])
    if parent is not None:
        console.print(Text(f"Paths below are relative to {display_path(parent)}", style="dim"))
    console.print()
    table = Table(box=None, show_edge=False, pad_edge=False, header_style="bold")
    table.add_column("", no_wrap=True)
    table.add_column("Worktree", overflow="fold")
    table.add_column("Branch", overflow="fold")
    table.add_column("Notes")
    for worktree in repository.worktrees:
        here = "*" if repository.current is not None and worktree.path == repository.current else ""
        shown = os.path.relpath(worktree.path, parent) if parent is not None else worktree.path
        table.add_row(
            Text(here), Text(display_path(shown)), Text(_ref(worktree)), Text(_notes(worktree))
        )
    console.print(table)
    if any(w.prunable is not None for w in repository.worktrees):
        console.print()
        console.print(
            Text(
                "Prunable worktrees are listed by Git but their directory is gone; "
                "worktree-shield never prunes them (git worktree prune would).",
                style="dim",
            )
        )
    line = redaction_line(snapshot)
    if line:
        console.print()
        console.print(Text(line, style="dim"))
