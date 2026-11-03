"""Listen ports in Procfiles and dev containers.

``Procfile`` and ``Procfile.dev`` (foreman, honcho, Heroku, Rails ``bin/dev``) hold one
``name: command`` per line; each command is scanned by
:func:`~worktree_shield.parsers.commands.listen_ports` and never run.

A dev container (``.devcontainer/devcontainer.json`` or ``.devcontainer.json``) can
publish ``appPort`` on the host, which fails when the port is taken, and forward
``forwardPorts`` to this machine, which the editor moves to another local port when it
is taken: those claims are not strict.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from worktree_shield.collectors.base import Collected, Scope, port_key
from worktree_shield.models import ResourceClaim, ResourceKind, SkippedFile
from worktree_shield.names import port_number
from worktree_shield.parsers.commands import listen_ports
from worktree_shield.parsers.jsonc import strip_jsonc

PROCFILES = ("Procfile", "Procfile.dev")
DEVCONTAINERS = (".devcontainer/devcontainer.json", ".devcontainer.json")
_PROCESS = re.compile(r"([A-Za-z0-9_-]+):\s*(.+)")


def collect_procfiles(scope: Scope, directory: PurePosixPath, out: Collected) -> None:
    """The listen ports of every process in the Procfiles of ``directory``."""
    for name in PROCFILES:
        relative = directory / name
        text = scope.read(relative, out)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            match = _PROCESS.fullmatch(line.strip())
            if match is None or line.lstrip().startswith("#"):
                continue
            process, command = match.groups()
            for mention in listen_ports(command):
                out.claims.append(
                    ResourceClaim(
                        ResourceKind.LISTEN_PORT,
                        port_key(mention.host, mention.port),
                        scope.worktree,
                        scope.source(relative, number),
                        f"{name} {process}: {mention.fragment}",
                        strict=mention.strict,
                    )
                )


def collect_devcontainer(scope: Scope, directory: PurePosixPath, out: Collected) -> None:
    """The ports a dev container in ``directory`` publishes or forwards."""
    for name in DEVCONTAINERS:
        relative = directory / name
        text = scope.read(relative, out)
        if text is None:
            continue
        plain = strip_jsonc(text)
        try:
            data = json.loads(plain)
        except json.JSONDecodeError as error:
            out.skipped.append(
                SkippedFile(scope.source(relative, error.lineno), "is not valid JSON")
            )
            continue
        if not isinstance(data, dict):
            continue
        finder = _Lines(plain)
        for key, strict in (("forwardPorts", False), ("appPort", True)):
            entries = _entries(data.get(key), single_allowed=key == "appPort")
            start = finder.key(key)
            for entry in entries:
                port = _port(entry, published=strict)
                if port is None:
                    continue
                host = "localhost" if key == "forwardPorts" else None
                out.claims.append(
                    ResourceClaim(
                        ResourceKind.LISTEN_PORT,
                        port_key(host, port),
                        scope.worktree,
                        scope.source(relative, finder.value(entry, start)),
                        f"{key}: {entry}",
                        strict=strict,
                    )
                )


def _entries(value: Any, *, single_allowed: bool) -> list[Any]:
    """The entries of a port list; appPort may also be a single port (the spec says so,
    forwardPorts must be an array)."""
    if isinstance(value, list):
        return value
    return [value] if single_allowed and value is not None else []


def _port(entry: Any, *, published: bool) -> int | None:
    """The local port of a forwardPorts or appPort entry: ``3000``, ``"db:5432"``
    (forwarded service port) or ``"8080:80"`` (published host:container)."""
    if isinstance(entry, bool):
        return None
    if isinstance(entry, int):
        return port_number(str(entry))
    if isinstance(entry, str):
        first, _, second = entry.partition(":")
        if not second:
            return port_number(first)
        return port_number(first if published else second)
    return None


class _Lines:
    """Lines of keys and array values in already parsed JSON text, found in order."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.position = 0

    def key(self, key: str) -> int:
        match = re.search(re.escape(json.dumps(key)) + r"\s*:", self.text)
        return match.end() if match else len(self.text)

    def value(self, entry: Any, start: int) -> int | None:
        literal = re.escape(json.dumps(entry)) if isinstance(entry, str) else rf"\b{entry}\b"
        match = re.compile(literal).search(self.text, max(start, self.position))
        if match is None:
            return None
        self.position = match.end()
        return self.text.count("\n", 0, match.start()) + 1
