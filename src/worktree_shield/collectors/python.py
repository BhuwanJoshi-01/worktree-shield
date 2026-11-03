"""Listen ports in the task runners of ``pyproject.toml``: poe, taskipy, pdm, hatch, rye.

The file is parsed with :mod:`tomllib`; task commands are scanned as text by
:func:`~worktree_shield.parsers.commands.listen_ports` and never run. Script tasks that
call Python functions (``script = "api:main"``) are not commands and are skipped. A
task's ``env`` table counts like a ``PORT=…`` prefix.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Any

from worktree_shield.collectors.base import Collected, Scope, port_key
from worktree_shield.models import ResourceClaim, ResourceKind, SkippedFile
from worktree_shield.names import port_number, port_variable
from worktree_shield.parsers.commands import PortMention, listen_ports

_MAX_DEPTH = 8  # sequences of sequences; real projects use two levels at most
_COMMAND_KEYS = ("cmd", "shell")
_SEQUENCE_KEYS = ("sequence", "composite", "chain")


def collect_pyproject(scope: Scope, directory: PurePosixPath, out: Collected) -> None:
    """The listen ports in the task runners of ``directory/pyproject.toml``."""
    relative = directory / "pyproject.toml"
    text = scope.read(relative, out)
    if text is None:
        return
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        out.skipped.append(SkippedFile(scope.source(relative), "is not valid TOML"))
        return
    found: list[ResourceClaim] = []
    for section, tasks in _task_tables(data):
        for name, task in tasks.items():
            line = _line(text, section, name)
            label = ".".join((*section, name))
            for mention in _mentions(task, 0):
                found.append(
                    ResourceClaim(
                        ResourceKind.LISTEN_PORT,
                        port_key(mention.host, mention.port),
                        scope.worktree,
                        scope.source(relative, line),
                        f"{label}: {mention.fragment}",
                        strict=mention.strict,
                    )
                )
    # In file order, whichever runner comes first; tasks without a known line last.
    out.claims += sorted(found, key=lambda claim: claim.source.line or len(text) + 1)


def _task_tables(data: dict[str, Any]) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return
    for runner, key in (
        ("poe", "tasks"),
        ("taskipy", "tasks"),
        ("pdm", "scripts"),
        ("rye", "scripts"),
    ):
        table = tool.get(runner)
        if isinstance(table, dict) and isinstance(table.get(key), dict):
            yield ("tool", runner, key), table[key]
    hatch = tool.get("hatch")
    envs = hatch.get("envs") if isinstance(hatch, dict) else None
    if isinstance(envs, dict):
        for env, settings in envs.items():
            if isinstance(settings, dict) and isinstance(settings.get("scripts"), dict):
                yield ("tool", "hatch", "envs", env, "scripts"), settings["scripts"]


def _mentions(task: Any, depth: int) -> list[PortMention]:
    """The listen ports of one task in any of the documented shapes."""
    if depth > _MAX_DEPTH:
        return []
    if isinstance(task, str):
        return listen_ports(task)
    if isinstance(task, list):
        return [m for item in task for m in _mentions(item, depth + 1)]
    if not isinstance(task, dict):
        return []
    found: list[PortMention] = []
    for key in _COMMAND_KEYS:
        command = task.get(key)
        if isinstance(command, str):
            found += listen_ports(command)
        elif isinstance(command, list) and all(isinstance(arg, str) for arg in command):
            found += listen_ports(shlex.join(command))  # an argument vector
    for key in _SEQUENCE_KEYS:
        if isinstance(task.get(key), list):
            found += _mentions(task[key], depth + 1)
    env = task.get("env")
    if isinstance(env, dict):
        for name, value in env.items():
            port = port_number(value) if isinstance(value, str) else None
            if port is not None and port_variable(name) is ResourceKind.LISTEN_PORT:
                found.append(PortMention(port, None, f"env.{name}={port}"))
    return found


def _line(text: str, section: tuple[str, ...], name: str) -> int | None:
    """The line defining task ``name``: its own ``[section.name]`` table, or a
    ``name = …`` line under ``[section]``. ``None`` when written some other way."""
    dotted = r"\s*\.\s*".join(_key_pattern(part) for part in section)
    own = re.compile(rf"^[ \t]*\[\s*{dotted}\s*\.\s*{_key_pattern(name)}\s*\]", re.M)
    if match := own.search(text):
        return text.count("\n", 0, match.start()) + 1
    header = re.compile(rf"^[ \t]*\[\s*{dotted}\s*\]", re.M).search(text)
    if header is None:
        return None
    following = re.compile(r"^[ \t]*\[", re.M).search(text, header.end())
    end = following.start() if following else len(text)
    key = re.compile(rf"^[ \t]*{_key_pattern(name)}\s*=", re.M).search(text, header.end(), end)
    return text.count("\n", 0, key.start()) + 1 if key else None


def _key_pattern(key: str) -> str:
    """A TOML key as written: bare, or in double or single quotes."""
    escaped = re.escape(key)
    return f"(?:{escaped}|\"{escaped}\"|'{escaped}')"
