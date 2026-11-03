"""Compose variable interpolation, resolved from the variables of the files read.

Implements the operators of the Compose specification: ``$VAR``, ``${VAR}``,
``${VAR:-default}`` / ``${VAR-default}``, ``${VAR:?error}`` / ``${VAR?error}``,
``${VAR:+replacement}`` / ``${VAR+replacement}``, nested defaults and ``$$`` for a
literal ``$``. Nothing is read from the environment of worktree-shield itself: the
shell that will run ``docker compose`` is not this one.

A variable that no file set is *assumed unset*: its default is used and the result
records the assumption, so a report can say "unless WEB_PORT is set in your shell". A
value that needs such a variable and has no default has no value (``None``) and the
variable is listed as *missing*; guessing an empty string, as Compose would, could
invent a collision.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPERATOR = re.compile(r":?[-?+]")
MAX_NESTING = 16  # ${A:-${B:-…}} levels; more is not a real configuration


@dataclass(frozen=True, slots=True)
class Interpolated:
    """The resolved text, or ``None`` when it depends on a missing variable or the
    syntax is invalid; ``missing`` and ``assumed_unset`` name variables in order."""

    value: str | None
    missing: tuple[str, ...] = ()
    assumed_unset: tuple[str, ...] = ()


class _Invalid(Exception):
    pass


class _Missing(Exception):
    pass


def interpolate(text: str, variables: Mapping[str, str]) -> Interpolated:
    """``text`` with every variable reference resolved from ``variables``."""
    resolver = _Resolver(variables, 0)
    try:
        value, _ = resolver.text(text, 0, closing=False)
    except _Invalid:
        return Interpolated(None)
    value_or_none = None if resolver.missing else value
    return Interpolated(value_or_none, tuple(resolver.missing), tuple(resolver.assumed))


class _Resolver:
    def __init__(self, variables: Mapping[str, str], depth: int) -> None:
        if depth > MAX_NESTING:
            raise _Invalid
        self.variables = variables
        self.depth = depth
        self.missing: list[str] = []
        self.assumed: list[str] = []

    def _note(self, names: list[str], name: str) -> None:
        if name not in names:
            names.append(name)

    def _adopt(self, child: _Resolver) -> None:
        """Take over what a default needed, once the default is actually used."""
        for name in child.assumed:
            self._note(self.assumed, name)
        for name in child.missing:
            self._note(self.missing, name)

    def text(self, text: str, index: int, *, closing: bool) -> tuple[str, int]:
        """Resolve from ``index`` to the end, or to the ``}`` closing a default when
        ``closing`` is set; returns the text and the index after it."""
        parts: list[str] = []
        while index < len(text):
            char = text[index]
            if closing and char == "}":
                return "".join(parts), index
            if char != "$":
                parts.append(char)
                index += 1
                continue
            following = text[index + 1 : index + 2]
            if following == "$":
                parts.append("$")
                index += 2
            elif following == "{":
                value, index = self.braced(text, index + 2)
                parts.append(value)
            elif name := _NAME.match(text, index + 1):
                parts.append(self.lookup(name.group(0)))
                index = name.end()
            else:  # a lone "$" is kept, as Compose keeps it
                parts.append("$")
                index += 1
        if closing:
            raise _Invalid
        return "".join(parts), index

    def lookup(self, name: str) -> str:
        if name in self.variables:
            return self.variables[name]
        self._note(self.missing, name)
        return ""

    def braced(self, text: str, index: int) -> tuple[str, int]:
        """``${…}`` starting after ``${``; returns its value and the index after ``}``."""
        name_match = _NAME.match(text, index)
        if name_match is None:
            raise _Invalid
        name, index = name_match.group(0), name_match.end()
        if text[index : index + 1] == "}":
            return self.lookup(name), index + 1
        operator_match = _OPERATOR.match(text, index)
        if operator_match is None:
            raise _Invalid
        operator = operator_match.group(0)
        default = _Resolver(self.variables, self.depth + 1)
        argument, end = default.text(text, operator_match.end(), closing=True)
        known = name in self.variables
        value = self.variables.get(name, "")
        is_set = known and (value != "" or not operator.startswith(":"))
        if operator.endswith("?"):
            if not is_set:
                self._note(self.missing, name)  # Compose would stop with the error
            return value, end + 1
        if not known:
            self._note(self.assumed, name)
        if operator.endswith("-"):
            if is_set:
                return value, end + 1
            self._adopt(default)
            return argument, end + 1
        if is_set:  # "+": the replacement only when the variable is set
            self._adopt(default)
            return argument, end + 1
        return "", end + 1
