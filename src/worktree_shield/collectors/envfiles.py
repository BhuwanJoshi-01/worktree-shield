"""Ports, databases and absolute paths declared in ``.env`` files.

Templates (``.env.example``, ``.env.sample``, ``.env.template``) are always read: they
are committed and meant to be shared. ``.env`` and ``.env.local`` hold real values,
often secrets, and are read only with ``include_env_files``. Either way a value leaves
this module only as a port number, a database without credentials or a path; the
values of every other variable are dropped.
"""

from __future__ import annotations

import ipaddress
from pathlib import PurePosixPath

from worktree_shield.collectors.base import Collected, Scope, is_absolute_path, path_key
from worktree_shield.models import (
    Policy,
    ResourceClaim,
    ResourceKind,
    SourceRef,
    UnreadableValue,
)
from worktree_shield.parsers.dburl import DatabaseURLError, parse_database_url
from worktree_shield.parsers.dotenv import EnvEntry, parse_dotenv

TEMPLATE_FILES = (".env.example", ".env.sample", ".env.template")
LOCAL_FILES = (".env", ".env.local")


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# A *_PORT with one of these words names a server the app connects to, not one it runs.
_CLIENT_WORDS = _words(
    "DB DATABASE POSTGRES POSTGRESQL PG MYSQL MARIADB REDIS MONGO MONGODB RABBITMQ AMQP SMTP "
    "MAIL EMAIL ELASTICSEARCH ELASTIC OPENSEARCH KAFKA MEMCACHED MINIO S3 NATS CLICKHOUSE"
)
_PATH_WORDS = _words(
    "DIR DIRECTORY PATH ROOT FOLDER CACHE OUT OUTPUT OUTDIR STORAGE UPLOAD UPLOADS DATA LOG "
    "LOGS TMP TEMP TMPDIR FILE LOCATION"
)
# Read-only by nature: search paths, installations, certificates and configuration.
_SEARCH_PATHS = _words(
    "PATH PYTHONPATH NODE_PATH LD_LIBRARY_PATH DYLD_LIBRARY_PATH MANPATH CLASSPATH GOPATH "
    "PKG_CONFIG_PATH CDPATH"
)
_READ_ONLY_WORDS = _words("HOME CERT CERTS KEY CA SSL TLS CONFIG CONF ETC")


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
        name = entry.key.upper()
        port = _port(value)
        if port is not None and (name == "PORT" or name.endswith("_PORT") or name == "PGPORT"):
            out.claims.append(_port_claim(scope, source, entry, port, by_name))
        elif _is_mutable_path_name(name) and is_absolute_path(value):
            detail = f"{entry.key}={value}"
            out.claims.append(
                ResourceClaim(
                    ResourceKind.ABSOLUTE_PATH, path_key(value), scope.worktree, source, detail
                )
            )


def _port_claim(
    scope: Scope, source: SourceRef, entry: EnvEntry, port: int, by_name: dict[str, EnvEntry]
) -> ResourceClaim:
    name = entry.key.upper()
    prefix = "PG" if name == "PGPORT" else name.removesuffix("PORT")
    host_entry = by_name.get(f"{prefix}HOST")
    host = _host(host_entry)
    client = name == "PGPORT" or bool(_CLIENT_WORDS.intersection(name.split("_")))
    kind = ResourceKind.CLIENT_ENDPOINT if client else ResourceKind.LISTEN_PORT
    server = host or ("localhost" if client else "*")
    shown = f"[{server}]" if ":" in server else server
    detail = f"{entry.key}={port}"
    if host_entry is not None and host is not None:
        detail += f" ({host_entry.key}={host_entry.value.strip()})"
    return ResourceClaim(kind, f"tcp://{shown}:{port}", scope.worktree, source, detail)


def _port(value: str) -> int | None:
    if not value.isascii() or not value.isdigit() or len(value) > 5:
        return None
    port = int(value)
    return port if 1 <= port <= 65535 else None


def _host(entry: EnvEntry | None) -> str | None:
    """A literal host name or address; ``None`` for references and anything odd."""
    if entry is None or entry.reference:
        return None
    value = entry.value.strip().lower()
    try:
        return str(ipaddress.ip_address(value.strip("[]")))
    except ValueError:
        pass
    labels = value.split(".")
    if value and all(label and label.replace("-", "").isalnum() for label in labels):
        return value if value.isascii() else None
    return None


def _is_mutable_path_name(name: str) -> bool:
    if name in _SEARCH_PATHS:
        return False
    words = set(name.split("_"))
    return bool(words & _PATH_WORDS) and not words & _READ_ONLY_WORDS
