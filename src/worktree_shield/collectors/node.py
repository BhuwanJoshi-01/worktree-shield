"""Listen ports in ``package.json``: every script, and npm's ``config.port``.

The file is parsed with :mod:`json`; scripts are scanned as text by
:func:`~worktree_shield.parsers.commands.listen_ports` and never run. Only the fragment
that names a port is kept, so other values on the same command line go nowhere.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import PurePosixPath

from worktree_shield.collectors.base import Collected, Scope, tcp_key
from worktree_shield.models import ResourceClaim, ResourceKind, SkippedFile
from worktree_shield.names import port_number
from worktree_shield.parsers.commands import listen_ports

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}\[\]:]', re.S)


def collect_package_json(scope: Scope, directory: PurePosixPath, out: Collected) -> None:
    """The listen ports in ``directory/package.json``, if there is one."""
    relative = directory / "package.json"
    text = scope.read(relative, out)
    if text is None:
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        out.skipped.append(SkippedFile(scope.source(relative, error.lineno), "is not valid JSON"))
        return
    if not isinstance(data, dict):
        return
    lines = _key_lines(text)

    def claim(port: int, host: str | None, key: tuple[str, str], detail: str) -> ResourceClaim:
        source = scope.source(relative, lines.get(key))
        resource = tcp_key(host, port)
        return ResourceClaim(ResourceKind.LISTEN_PORT, resource, scope.worktree, source, detail)

    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        for name, command in scripts.items():
            if isinstance(command, str):
                for mention in listen_ports(command):
                    found = claim(
                        mention.port,
                        mention.host,
                        ("scripts", name),
                        f"scripts.{name}: {mention.fragment}",
                    )
                    out.claims.append(replace(found, strict=mention.strict))
    config = data.get("config")
    if isinstance(config, dict):
        value = config.get("port")
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            port = port_number(str(value))
            if port is not None:
                out.claims.append(claim(port, None, ("config", "port"), f"config.port={port}"))


def _key_lines(text: str) -> dict[tuple[str, ...], int]:
    """The line of every object key, by its path (``("scripts", "dev")``); for a key
    defined twice the later line, as :mod:`json` keeps the later value."""
    lines: dict[tuple[str, ...], int] = {}
    tokens = list(_TOKEN.finditer(text))
    opened_by: list[str | None] = []  # the key whose value each open container is
    last_key: str | None = None
    line, position = 1, 0
    for index, match in enumerate(tokens):
        piece = match.group()
        if piece.startswith('"'):
            if index + 1 < len(tokens) and tokens[index + 1].group() == ":":
                last_key = json.loads(piece)
                line += text.count("\n", position, match.start())
                position = match.start()
                path = tuple(key for key in opened_by if key is not None)
                lines[(*path, last_key)] = line
        elif piece in "{[":
            opened_by.append(last_key)
            last_key = None
        elif piece in "}]":
            opened_by.pop()  # balanced: json.loads() accepted the text
            last_key = None
    return lines
