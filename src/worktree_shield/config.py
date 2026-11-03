"""The repository policy, ``.worktree-shield.toml``: TOML read as data, never run.

Precedence is flags, then the file in the current worktree, then the defaults in
:class:`~worktree_shield.models.Policy`; there is no user-wide policy. Anything the
parser does not know is an error rather than a silent default, so a misspelt key cannot
quietly turn a ``deny`` back into a ``warn``.
"""

from __future__ import annotations

import dataclasses
import os
import stat
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from worktree_shield.models import Policy, PolicyLevel, Repository

POLICY_FILE = ".worktree-shield.toml"
MAX_POLICY_BYTES = 64 * 1024
SCHEMA_VERSION = 1
MAX_FILE_BYTES_LIMIT = 16 * 1024 * 1024

_SCAN_FLAGS = ("include_runtime", "include_env_files")
_LEVELS = (
    "shared_host_ports",
    "shared_database",
    "shared_compose_projects",
    "fixed_container_names",
    "shared_absolute_paths",
)
_SECTIONS: dict[str, tuple[str, ...]] = {
    "scan": (*_SCAN_FLAGS, "max_file_bytes"),
    "policy": _LEVELS,
    "allow": ("ports", "paths"),
}


class PolicyError(Exception):
    """The policy file cannot be used; the message names the file and the problem."""


def parse_policy(text: str, source: str) -> Policy:
    """The policy in ``text``; ``source`` names the file in messages and in the result."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise PolicyError(f"{source} is not valid TOML: {error}") from None
    try:
        return _policy(data, source)
    except _Invalid as error:
        raise PolicyError(f"{source}: {error}") from None


def load_policy(worktree: Path) -> Policy:
    """The policy of a worktree, or the defaults when it has no policy file.

    The file must be a regular file inside the worktree (a link may point elsewhere in
    it) and at most :data:`MAX_POLICY_BYTES` long.
    """
    path = worktree / POLICY_FILE
    if not os.path.lexists(path):
        return Policy()
    try:
        target = path.resolve(strict=True)
        if not target.is_relative_to(worktree.resolve(strict=True)):
            raise PolicyError(f"{path} links to a file outside the worktree; it was not read")
        if not stat.S_ISREG(target.stat().st_mode):
            raise PolicyError(f"{path} is not a regular file")
        with target.open("rb") as handle:
            raw = handle.read(MAX_POLICY_BYTES + 1)
    except OSError as error:
        raise PolicyError(f"{path} could not be read: {error.strerror or error}") from None
    if len(raw) > MAX_POLICY_BYTES:
        raise PolicyError(f"{path} is larger than {MAX_POLICY_BYTES} bytes; it was not read")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PolicyError(f"{path} is not UTF-8 text") from None
    return parse_policy(text, str(path))


def policy_of(repository: Repository) -> Policy:
    """The policy of the current worktree; a bare repository has the defaults only."""
    if repository.current is None:
        return Policy()
    return load_policy(Path(repository.current))


def apply_overrides(
    policy: Policy,
    *,
    include_runtime: bool | None = None,
    include_env_files: bool | None = None,
) -> Policy:
    """The policy with the settings given on the command line; ``None`` keeps the file's."""
    changes: dict[str, Any] = {}
    if include_runtime is not None:
        changes["include_runtime"] = include_runtime
    if include_env_files is not None:
        changes["include_env_files"] = include_env_files
    return dataclasses.replace(policy, **changes) if changes else policy


class _Invalid(Exception):
    pass


def _policy(data: dict[str, Any], source: str) -> Policy:
    for key, value in data.items():
        if key == "schema_version":
            continue
        if key not in _SECTIONS:
            unknown = f"section [{key}]" if isinstance(value, dict) else f"key {key}"
            raise _Invalid(f"unknown {unknown}")
        if not isinstance(value, dict):
            raise _Invalid(f"{key} must be a section, written [{key}]")
        for name in value:
            if name not in _SECTIONS[key]:
                raise _Invalid(f"unknown key {key}.{name}")
    _schema_version(data)
    scan = data.get("scan", {})
    levels = data.get("policy", {})
    allow = data.get("allow", {})
    settings: dict[str, Any] = {name: _flag(scan, name) for name in _SCAN_FLAGS if name in scan}
    if "max_file_bytes" in scan:
        settings["max_file_bytes"] = _max_file_bytes(scan["max_file_bytes"])
    settings |= {name: _level(levels, name) for name in _LEVELS if name in levels}
    if "ports" in allow:
        settings["allow_ports"] = _ports(allow["ports"])
    if "paths" in allow:
        settings["allow_paths"] = _paths(allow["paths"])
    return Policy(**settings, source=source)


def _schema_version(data: dict[str, Any]) -> None:
    if "schema_version" not in data:
        raise _Invalid(
            f"schema_version is missing; start the file with schema_version = {SCHEMA_VERSION}"
        )
    version = data["schema_version"]
    if not _is_int(version):
        raise _Invalid(f"schema_version must be the number {SCHEMA_VERSION}, not {_shown(version)}")
    if version != SCHEMA_VERSION:
        raise _Invalid(
            f"schema_version {version} is not supported; this version reads {SCHEMA_VERSION}"
        )


def _flag(section: dict[str, Any], name: str) -> bool:
    value = section[name]
    if not isinstance(value, bool):
        raise _Invalid(f"scan.{name} must be true or false, not {_shown(value)}")
    return value


def _max_file_bytes(value: Any) -> int:
    if not _is_int(value) or not 1 <= value <= MAX_FILE_BYTES_LIMIT:
        raise _Invalid(
            f"scan.max_file_bytes must be a whole number from 1 to {MAX_FILE_BYTES_LIMIT}, "
            f"not {_shown(value)}"
        )
    result: int = value
    return result


def _level(section: dict[str, Any], name: str) -> PolicyLevel:
    value = section[name]
    allowed = ", ".join(level.value for level in PolicyLevel)
    if not isinstance(value, str) or value not in {level.value for level in PolicyLevel}:
        raise _Invalid(f"policy.{name} must be one of {allowed}, not {_shown(value)}")
    return PolicyLevel(value)


def _ports(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list) or not all(_is_int(p) and 1 <= p <= 65535 for p in value):
        raise _Invalid("allow.ports must be port numbers from 1 to 65535 in a list, like [5432]")
    return tuple(sorted(set(value)))


def _paths(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(_is_absolute(p) for p in value):
        raise _Invalid('allow.paths must be absolute paths in a list, like ["/srv/cache"]')
    return tuple(dict.fromkeys(value))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_absolute(value: Any) -> bool:
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _shown(value: Any) -> str:
    """A value from the file for a message: repr() escapes control characters."""
    shown = repr(value)
    return shown if len(shown) <= 40 else shown[:39] + "…"
