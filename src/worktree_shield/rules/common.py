"""Pieces the rule modules share: key parsing, evidence and finding helpers."""

from __future__ import annotations

import re

from worktree_shield.models import (
    Confidence,
    Evidence,
    Finding,
    ResourceClaim,
    Severity,
    SourceRef,
    Status,
)

VERIFY = "worktree-shield scan --strict"
_PORT = re.compile(r"[a-z]+://.*:([0-9]+)")


def port_of(key: str) -> int | None:
    """The port of a ``tcp://host:port`` or ``db://engine/host:port/db`` key."""
    match = _PORT.fullmatch(key.rsplit("/", 1)[0] if key.startswith("db://") else key)
    return int(match.group(1)) if match else None


def name_of(key: str) -> str:
    """What follows the scheme: ``shop`` of ``compose-project://shop``."""
    return key.split("://", 1)[-1]


def where(source: SourceRef) -> str:
    return source.path if source.line is None else f"{source.path}:{source.line}"


def evidence(claims: tuple[ResourceClaim, ...] | list[ResourceClaim]) -> tuple[Evidence, ...]:
    """One line per claim: where it was found, in which worktree, what was read."""
    return tuple(Evidence(where(c.source), c.worktree, c.detail) for c in claims)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def plain(rule: str, status: Status, summary: str, reason: str) -> Finding:
    """A finding about no resource in particular: nothing to check, or nothing found."""
    return Finding(rule, status, Severity.INFO, Confidence.MEDIUM, summary, reason)
