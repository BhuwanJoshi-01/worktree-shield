"""Literal listen ports in script command lines, found by reading the text.

Nothing is run or expanded. A command is split like a POSIX shell would split it,
cut at ``&&``, ``||``, ``;``, ``|`` and ``&``, and each part is searched for the
spellings dev servers use: ``--port 5173``, ``-p 3001``, ``-l 5000``,
``--bind 127.0.0.1:8000``, ``-S localhost:8000``, ``PORT=4000 node …`` and the
argument of ``runserver`` or ``http.server``. Quoted arguments that are commands
themselves (``concurrently 'vite --port 5173' …``) are searched too.

A port given through a variable (``--port $PORT``) is not literal and is skipped; the
variable's own definition is where the collectors find it. In a part that runs a client
(``psql -p 5432``, ``ssh -p 2222``) the flags name a server to connect to and are
ignored.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath

from worktree_shield.models import ResourceKind
from worktree_shield.names import literal_host, port_number, port_variable

_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", ";;", "(", ")"})
_PORT_FLAGS = frozenset({"--port", "-p", "--listen", "-l"})
_BIND_FLAGS = frozenset({"--bind", "-b", "-S"})
_HOST_FLAGS = frozenset({"--host", "--hostname", "-H"})
_PORT_ARGUMENT_AFTER = frozenset({"runserver", "http.server"})
_CLIENT_PROGRAMS = frozenset(
    {
        "psql",
        "pg_dump",
        "pg_restore",
        "pg_isready",
        "mysql",
        "mysqldump",
        "mysqladmin",
        "redis-cli",
        "mongosh",
        "mongo",
        "ssh",
        "scp",
        "sftp",
        "nc",
        "telnet",
        "curl",
        "wget",
        "docker",
        "podman",
        "kubectl",
    }
)
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MAX_DEPTH = 3


@dataclass(frozen=True, slots=True)
class PortMention:
    """A listen port in a command; ``fragment`` is the part that names it (never the
    whole command, which may carry other values). ``strict`` is set for Vite: ``True``
    with ``--strictPort``, otherwise ``False`` (it moves to the next free port)."""

    port: int
    host: str | None
    fragment: str
    strict: bool | None = None


def listen_ports(command: str) -> list[PortMention]:
    """Every literal listen port in ``command``, in order."""
    return _scan(command, 0)


def _scan(command: str, depth: int) -> list[PortMention]:
    found: list[PortMention] = []
    part: list[str] = []
    for token in [*_tokens(command), ";"]:
        if token in _SEPARATORS:
            found += _scan_part(part, depth)
            part = []
        else:
            part.append(token)
    return found


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:  # an unclosed quote: words are still worth a look
        return command.split()


def _scan_part(part: list[str], depth: int) -> list[PortMention]:
    if any(PurePosixPath(token).name in _CLIENT_PROGRAMS for token in part):
        return []
    strict = None
    if any(PurePosixPath(token).name == "vite" for token in part):
        strict = "--strictPort" in part or "--strict-port" in part
    host = _host_option(part)
    found: list[PortMention] = []
    for index, token in enumerate(part):
        following = part[index + 1] if index + 1 < len(part) else None
        if any(c.isspace() for c in token):
            if depth < _MAX_DEPTH:
                found += _scan(token, depth + 1)
            continue
        name, equals, value = token.partition("=")
        if equals and _VARIABLE.fullmatch(name):
            port = port_number(value)
            if port is not None and port_variable(name) is ResourceKind.LISTEN_PORT:
                found.append(PortMention(port, None, token, None))
            continue
        argument: str | None
        if equals and name.startswith("-"):
            flag, argument, fragment = name, value, token
        else:
            flag, argument, fragment = token, following, f"{token} {following}"
        if argument is None:
            continue
        if flag in _PORT_FLAGS:
            port = port_number(argument)
            if port is not None:
                found.append(PortMention(port, host, fragment, strict))
        elif flag in _BIND_FLAGS or flag in _PORT_ARGUMENT_AFTER:
            address = _address(argument)
            if address is not None:
                found.append(PortMention(address[1], address[0], fragment, strict))
    return found


def _host_option(part: list[str]) -> str | None:
    for index, token in enumerate(part):
        name, equals, value = token.partition("=")
        if equals and name in _HOST_FLAGS:
            return literal_host(value)
        if token in _HOST_FLAGS and index + 1 < len(part):
            return literal_host(part[index + 1])
    return None


def _address(text: str) -> tuple[str | None, int] | None:
    """``127.0.0.1:8000``, ``[::1]:8000``, ``:8000`` or ``8000`` as host and port."""
    host_text, colon, port_text = text.rpartition(":")
    if not colon:
        port = port_number(text)
        return (None, port) if port is not None else None
    port = port_number(port_text)
    if port is None:
        return None
    if not host_text:
        return None, port
    host = literal_host(host_text)
    return (host, port) if host is not None else None
