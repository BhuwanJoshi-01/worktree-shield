"""Rules, how they are run, and how a policy level and a certainty become a status."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from worktree_shield.collisions import find_collisions
from worktree_shield.models import (
    Certainty,
    Collision,
    Confidence,
    Finding,
    Policy,
    PolicyLevel,
    Snapshot,
    Status,
)


@dataclass(frozen=True, slots=True)
class Context:
    """What every rule sees: the snapshot, the effective policy and the collisions."""

    snapshot: Snapshot
    policy: Policy
    collisions: tuple[Collision, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class Rule:
    """One WTS rule. ``title`` is the one-line description in ``rules list`` and the docs."""

    id: str
    title: str
    check: Callable[[Context], Iterable[Finding]]


def evaluate(snapshot: Snapshot, rules: Sequence[Rule]) -> tuple[Finding, ...]:
    """The findings of every rule, in catalog order."""
    context = Context(snapshot, snapshot.policy or Policy(), find_collisions(snapshot.claims))
    return tuple(finding for rule in rules for finding in rule.check(context))


def status_for(level: PolicyLevel, certainty: Certainty) -> Status:
    """``deny`` fails what is confirmed or probable, ``warn`` warns, ``allow`` passes.
    A possible collision only ever warns: failing CI on a guess helps nobody."""
    if level is PolicyLevel.ALLOW:
        return Status.PASS
    if level is PolicyLevel.DENY and certainty in (Certainty.CONFIRMED, Certainty.PROBABLE):
        return Status.FAIL
    return Status.WARN


def confidence_for(certainty: Certainty) -> Confidence:
    if certainty is Certainty.CONFIRMED:
        return Confidence.HIGH
    if certainty is Certainty.PROBABLE:
        return Confidence.MEDIUM
    return Confidence.LOW
