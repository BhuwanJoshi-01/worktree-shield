"""Ports, databases and absolute paths declared in ``.env`` files.

Templates (``.env.example``, ``.env.sample``, ``.env.template``) are always read: they
are committed and meant to be shared. ``.env`` and ``.env.local`` hold real values,
often secrets, and are read only with ``include_env_files``; then a key they set
replaces the templates' value for it, as dotenv tools load ``.env.local`` over ``.env``
and never read a template. Either way a value leaves
this module only as a port number, a database without credentials or a path; the
values of every other variable are dropped.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from worktree_shield.collectors.base import (
    Collected,
    Scope,
    is_absolute_path,
    path_key,
    port_key,
)
from worktree_shield.models import (
    Policy,
    ResourceClaim,
    ResourceKind,
    SkippedFile,
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
NOT_READ = "was not read: .env files are read only with --include-env"


def collect_env_files(
    scope: Scope, directory: PurePosixPath, policy: Policy, out: Collected
) -> None:
    """The claims of the ``.env`` files in one directory of a worktree."""
    names = TEMPLATE_FILES + (LOCAL_FILES if policy.include_env_files else ())
    if not policy.include_env_files:
        folder = Path(scope.root, *directory.parts)
        for name in LOCAL_FILES:  # noted, not opened: what runs may differ from what was read
            if os.path.lexists(folder / name):
                out.skipped.append(SkippedFile(scope.source(directory / name), NOT_READ))
    files: list[tuple[PurePosixPath, tuple[EnvEntry, ...]]] = []
    for name in names:
        relative = directory / name
        text = scope.read(relative, out)
        if text is not None:
            files.append((relative, parse_dotenv(text)))
    for index, (relative, entries) in enumerate(files):
        later = files[index + 1 :]  # in names order: templates, then .env, then .env.local
        overridden = {
            e.key.upper() for path, found in later if path.name in LOCAL_FILES for e in found
        }
        _collect(scope, relative, entries, out, skip=overridden)


def _collect(
    scope: Scope,
    relative: PurePosixPath,
    entries: tuple[EnvEntry, ...],
    out: Collected,
    *,
    skip: set[str],
) -> None:
    """The claims of one file, except for keys a higher-priority local file sets."""
    by_name = {entry.key.upper(): entry for entry in entries}
    for entry in entries:
        if entry.reference or entry.key.upper() in skip:
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
            detail = entry.key  # the key already names the database
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
    return ResourceClaim(kind, port_key(host, port, default), scope.worktree, source, detail)
