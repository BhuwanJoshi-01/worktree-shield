"""Terminal output of an already redacted snapshot.

Collected text (paths, branch names, lock reasons) is added as plain ``Text``, never as
Rich markup, so a branch called ``[bold]x`` is printed as it is.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from worktree_shield.models import (
    Policy,
    Repository,
    ResourceClaim,
    ResourceKind,
    Snapshot,
    SourceRef,
    Worktree,
)

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


def _policy_rows(policy: Policy) -> list[tuple[str, str, str]]:
    """(setting, value, default value) in the order of the policy file."""
    default = Policy()

    def flag(value: bool) -> str:
        return "true" if value else "false"

    def listed(values: tuple[object, ...]) -> str:
        return ", ".join(display_path(str(v)) for v in values) if values else "none"

    return [
        ("scan.include_runtime", flag(policy.include_runtime), flag(default.include_runtime)),
        ("scan.include_env_files", flag(policy.include_env_files), flag(default.include_env_files)),
        ("scan.max_file_bytes", str(policy.max_file_bytes), str(default.max_file_bytes)),
        ("policy.shared_host_ports", policy.shared_host_ports, default.shared_host_ports),
        ("policy.shared_database", policy.shared_database, default.shared_database),
        (
            "policy.shared_compose_projects",
            policy.shared_compose_projects,
            default.shared_compose_projects,
        ),
        (
            "policy.fixed_container_names",
            policy.fixed_container_names,
            default.fixed_container_names,
        ),
        (
            "policy.shared_absolute_paths",
            policy.shared_absolute_paths,
            default.shared_absolute_paths,
        ),
        ("allow.ports", listed(policy.allow_ports), listed(default.allow_ports)),
        ("allow.paths", listed(policy.allow_paths), listed(default.allow_paths)),
    ]


def render_policy(policy: Policy, worktree: str | None, console: Console) -> None:
    """The effective policy of a worktree and where each value comes from."""
    if policy.source is not None:
        console.print(Text(f"Policy from {display_path(policy.source)}", style="bold"))
    elif worktree is not None:
        console.print(Text("Built-in defaults", style="bold"))
        console.print(Text(f"No .worktree-shield.toml in {display_path(worktree)}", style="dim"))
    else:
        console.print(
            Text("Built-in defaults (a bare repository has no policy file)", style="bold")
        )
    console.print()
    table = Table(box=None, show_edge=False, pad_edge=False, header_style="bold")
    table.add_column("Setting", no_wrap=True)
    table.add_column("Value", overflow="fold")
    table.add_column("")
    for name, value, default in _policy_rows(policy):
        note = "" if value == default or policy.source is None else f"default: {default}"
        table.add_row(Text(name), Text(str(value)), Text(note, style="dim"))
    console.print(table)
    console.print()
    console.print(
        Text(
            "deny fails --strict, warn is reported, allow is information only. allow.ports "
            "are endpoints the worktrees may share as clients; two listeners on one port are "
            "never allowed by it.",
            style="dim",
        )
    )


_KIND_TITLES = (
    (ResourceKind.LISTEN_PORT, "Listen ports"),
    (ResourceKind.DATABASE, "Databases"),
    (ResourceKind.COMPOSE_PROJECT, "Compose projects"),
    (ResourceKind.CONTAINER_NAME, "Container names"),
    (ResourceKind.VOLUME, "Volumes"),
    (ResourceKind.ABSOLUTE_PATH, "Absolute paths"),
    (ResourceKind.CLIENT_ENDPOINT, "Servers the worktrees connect to"),
)


def _where(source: SourceRef) -> str:
    line = f":{source.line}" if source.line is not None else ""
    return display_path(source.path) + line


def worktree_names(repository: Repository) -> tuple[Callable[[str], str], str | None]:
    """How reports name a worktree (relative to the directory all of them share) and
    that directory, if any."""
    parent = common_parent([w.path for w in repository.worktrees])

    def name(worktree: str) -> str:
        return display_path(os.path.relpath(worktree, parent) if parent is not None else worktree)

    return name, parent


def render_failed_discovery(snapshot: Snapshot, console: Console) -> None:
    console.print(Text("The worktrees could not be listed:"))
    for failure in snapshot.probe_failures:
        console.print(Text(f"  {failure.probe}: {failure.detail}"))


def render_resources(snapshot: Snapshot, console: Console) -> None:
    """Every resource the worktrees declare, grouped by kind; shared ones marked."""
    repository = snapshot.repository
    console.print(Text(f"worktree-shield {snapshot.tool_version}", style="bold"))
    if repository is None:
        render_failed_discovery(snapshot, console)
        return
    name, parent = worktree_names(repository)

    by_key: dict[tuple[ResourceKind, str], list[ResourceClaim]] = defaultdict(list)
    for claim in snapshot.claims:
        by_key[(claim.kind, claim.key)].append(claim)
    shared = sum(1 for claims in by_key.values() if len({c.worktree for c in claims}) > 1)
    count = len(repository.worktrees)
    console.print(
        Text(
            f"{count} worktree{'s' if count != 1 else ''}, {len(by_key)} "
            f"resource{'s' if len(by_key) != 1 else ''}, {shared} used by more than one worktree"
        )
    )
    if parent is not None:
        console.print(Text(f"Worktrees are named relative to {display_path(parent)}", style="dim"))
    for kind, title in _KIND_TITLES:
        keys = sorted(key for key in by_key if key[0] is kind)
        if not keys:
            continue
        console.print()
        console.print(Text(title, style="bold"))
        table = Table(box=None, show_edge=False, pad_edge=False, show_header=False)
        table.add_column("Resource", no_wrap=True)
        table.add_column("Worktree", overflow="fold")
        table.add_column("Where", overflow="fold")
        table.add_column("What", overflow="fold")
        for key in keys:
            claims = by_key[key]
            users = len({c.worktree for c in claims})
            label = Text(key[1])
            if users > 1:
                label.append(f"  {users} worktrees", style="bold yellow")
            for index, claim in enumerate(claims):
                table.add_row(
                    label if index == 0 else Text(""),
                    Text(name(claim.worktree)),
                    Text(_where(claim.source)),
                    Text(claim.detail),
                )
        console.print(table)
    if not by_key:
        console.print()
        console.print(Text("No ports, databases or paths were found in the configuration."))
    _render_gaps(snapshot, name, console)


def _render_gaps(snapshot: Snapshot, label: Callable[[str], str], console: Console) -> None:
    """What could not be read: skipped files, unreadable values, files left out."""
    if snapshot.skipped:
        console.print()
        console.print(Text("Not read", style="bold"))
        for skipped in snapshot.skipped:
            where = _where(skipped.source)
            console.print(Text(f"  {label(skipped.source.worktree)}  {where} {skipped.reason}"))
    if snapshot.unreadable:
        console.print()
        console.print(Text("Could not be identified", style="bold"))
        for value in snapshot.unreadable:
            where = _where(value.source)
            console.print(
                Text(f"  {label(value.source.worktree)}  {where} {value.name}: {value.reason}")
            )
    runtime = snapshot.runtime
    if runtime is not None and runtime.unattributed:
        console.print()
        console.print(Text("Configured ports in use outside the worktrees", style="bold"))
        for listener in runtime.unattributed:
            owner = listener.process or "a process"
            if listener.pid is not None:
                owner += f" (pid {listener.pid})"
            address = f"[{listener.address}]" if ":" in listener.address else listener.address
            console.print(
                Text(f"  {listener.protocol} {address}:{listener.port}  {owner}: {listener.note}")
            )
    if runtime is not None:
        for limitation in runtime.limitations:
            console.print(Text(f"Running processes: {limitation}.", style="dim"))
    elif snapshot.policy is not None:
        console.print()
        console.print(Text("Running processes were not looked at.", style="dim"))
    line = redaction_line(snapshot)
    if line:
        console.print()
        console.print(Text(line, style="dim"))
