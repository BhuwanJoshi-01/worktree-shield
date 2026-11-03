"""Ports, databases and absolute paths declared in ``.env`` files.

Templates (``.env.example``, ``.env.sample``, ``.env.template``) are always read: they
are committed and meant to be shared. ``.env`` and ``.env.local`` hold real values,
often secrets, and are read only with ``include_env_files``. Either way a value leaves
this module only as a port number, a database without credentials or a path; the
values of every other variable are dropped.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from worktree_shield.collectors.base import (
    Collected,
    Scope,
    is_absolute_path,
    path_key,
    tcp_key,
)
from worktree_shield.models import (
    Policy,
    ResourceClaim,
    ResourceKind,
    SourceRef,
    UnreadableValue,
)
from worktree_shield.names import (
    host_variable,
    is_mutable_path_variable,
    literal_host,
    port_number,
    port_variable,
)
from worktree_shield.parsers.dburl import DatabaseURLError, parse_database_url
from worktree_shield.parsers.dotenv import EnvEntry, parse_dotenv

TEMPLATE_FILES = (".env.example", ".env.sample", ".env.template")
LOCAL_FILES = (".env", ".env.local")


def collect_env_files(
    scope: Scope, directory: PurePosixPath, policy: Policy, out: Collected
) -> None:
    """The claims of the ``.env`` files in one directory of a worktree."""
    names = TEMPLATE_FILES + (LOCAL_FILES if policy.include_env_files else ())
    for name in names:
        relative = directory / name
        text = scope.read(relative, out)
        if text is not None:
            _collect(scope, relative, parse_dotenv(text), out)


def _collect(
    scope: Scope, relative: PurePosixPath, entries: tuple[EnvEntry, ...], out: Collected
) -> None:
    by_name = {entry.key.upper(): entry for entry in entries}
    for entry in entries:
        if entry.reference:
            continue
        value = entry.value.strip()
        source = scope.source(relative, entry.line)
        try:
            target = parse_database_url(value)
        except DatabaseURLError as error:
            out.unreadable.append(
                UnreadableValue(ResourceKind.DATABASE, source, entry.key, str(error))
            )
            continue
        if target is not None:
            if target.engine == "sqlite" and not is_absolute_path(target.database or ""):
                continue  # relative to each worktree, so never shared
            detail = f"{entry.key} points to {target.key}"
            out.claims.append(
                ResourceClaim(ResourceKind.DATABASE, target.key, scope.worktree, source, detail)
            )
            continue
        port = port_number(value)
        kind = port_variable(entry.key)
        if port is not None and kind is not None:
            out.claims.append(_port_claim(scope, source, entry, kind, port, by_name))
        elif is_mutable_path_variable(entry.key) and is_absolute_path(value):
            detail = f"{entry.key}={value}"
            out.claims.append(
                ResourceClaim(
                    ResourceKind.ABSOLUTE_PATH, path_key(value), scope.worktree, source, detail
                )
            )


def _port_claim(
    scope: Scope,
    source: SourceRef,
    entry: EnvEntry,
    kind: ResourceKind,
    port: int,
    by_name: dict[str, EnvEntry],
) -> ResourceClaim:
    host_entry = by_name.get(host_variable(entry.key))
    host = None
    if host_entry is not None and not host_entry.reference:
        host = literal_host(host_entry.value)
    default = "localhost" if kind is ResourceKind.CLIENT_ENDPOINT else "*"
    detail = f"{entry.key}={port}"
    if host_entry is not None and host is not None:
        detail += f" ({host_entry.key}={host_entry.value.strip()})"
    return ResourceClaim(kind, tcp_key(host, port, default), scope.worktree, source, detail)
