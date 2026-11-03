"""Ports and paths in ``vite.config.*``, matched as text; the config is never run.

Only literal settings count: ``server.port`` and ``preview.port`` (with ``host`` and
``strictPort`` from the same block), ``cacheDir`` and ``build.outDir`` when absolute. A
port computed from the environment (``Number(process.env.PORT)``) is left to the
collector that reads the variable. Comments, strings and template literals are blanked
first, so a commented-out block or a string that looks like one is ignored.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from worktree_shield.collectors.base import Collected, Scope, is_absolute_path, path_key, port_key
from worktree_shield.models import ResourceClaim, ResourceKind
from worktree_shield.names import literal_host, port_number
from worktree_shield.parsers.jstext import blank_code

CONFIG_FILES = tuple(f"vite.config.{ext}" for ext in ("js", "ts", "mjs", "mts", "cjs", "cts"))
_BLOCK = re.compile(r"\b(server|preview|build)\s*:\s*\{")
_SETTING = re.compile(r"\b(port|host|strictPort|outDir)\s*:\s*")
_CACHE_DIR = re.compile(r"\bcacheDir\s*:\s*")
_END = r"(?=\s*(?:,|\}|\n|$))"  # the literal is the whole value
_NUMBER = re.compile(r"([0-9]+)" + _END)
_BOOLEAN = re.compile(r"(true|false)" + _END)

_Value = str | int | bool


def collect_vite_config(scope: Scope, directory: PurePosixPath, out: Collected) -> None:
    """The claims of every ``vite.config.*`` in ``directory``."""
    for name in CONFIG_FILES:
        relative = directory / name
        text = scope.read(relative, out)
        if text is not None:
            out.claims += _claims(scope, relative, text)


def _claims(scope: Scope, relative: PurePosixPath, text: str) -> list[ResourceClaim]:
    code = blank_code(text)
    ports: list[ResourceClaim] = []
    paths: list[tuple[int, ResourceClaim]] = []

    def line(position: int) -> int:
        return text.count("\n", 0, position) + 1

    def path_claim(position: int, label: str, value: _Value | None) -> None:
        if isinstance(value, str) and is_absolute_path(value):
            source = scope.source(relative, line(position))
            claim = ResourceClaim(
                ResourceKind.ABSOLUTE_PATH,
                path_key(value),
                scope.worktree,
                source,
                f"{label}: {value}",
            )
            paths.append((position, claim))

    for block in _BLOCK.finditer(code):
        settings = _settings(code, text, block.end() - 1)
        kind = block.group(1)
        if kind == "build":
            if "outDir" in settings:
                value, position = settings["outDir"]
                path_claim(position, "build.outDir", value)
            continue
        if "port" not in settings:
            continue
        value, position = settings["port"]
        port = (
            port_number(str(value))
            if isinstance(value, int) and not isinstance(value, bool)
            else None
        )
        if port is None:
            continue
        host_value = settings.get("host", (None, 0))[0]
        host = literal_host(host_value) if isinstance(host_value, str) else None
        strict = settings.get("strictPort", (False, 0))[0] is True
        source = scope.source(relative, line(position))
        ports.append(
            ResourceClaim(
                ResourceKind.LISTEN_PORT,
                port_key(host, port),
                scope.worktree,
                source,
                f"{kind}.port: {port}",
                strict=strict,
            )
        )
    for match in _CACHE_DIR.finditer(code):
        path_claim(match.start(), "cacheDir", _literal(code, text, match.end()))
    return ports + [claim for _, claim in sorted(paths, key=lambda item: item[0])]


def _settings(code: str, text: str, opening: int) -> dict[str, tuple[_Value | None, int]]:
    """The literal settings directly inside the object that opens at ``opening``
    (nested objects such as ``hmr: { port }`` are skipped); empty if it never closes."""
    depth = 0
    found: dict[str, tuple[_Value | None, int]] = {}
    index = opening + 1
    while index < len(code):
        char = code[index]
        if char in "{[(":
            depth += 1
        elif char in "}])":
            if depth == 0:
                return found
            depth -= 1
        elif depth == 0 and (match := _SETTING.match(code, index)) and _starts_word(code, index):
            found[match.group(1)] = (_literal(code, text, match.end()), index)
            index = match.end()
            continue
        index += 1
    return {}


def _starts_word(code: str, index: int) -> bool:
    return index == 0 or not (code[index - 1].isalnum() or code[index - 1] in "_$")


def _literal(code: str, text: str, position: int) -> _Value | None:
    """A number, boolean or string literal that is the whole value at ``position``."""
    if number := _NUMBER.match(code, position):
        return int(number.group(1))
    if boolean := _BOOLEAN.match(code, position):
        return boolean.group(1) == "true"
    if position < len(code) and code[position] in "'\"":
        closing = code.find(code[position], position + 1)
        if closing > 0 and re.match(_END, code[closing + 1 :]):
            return text[position + 1 : closing]
    return None
