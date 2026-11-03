"""Rules about what is running now: ports held by servers or other processes."""

from __future__ import annotations

from collections.abc import Iterator

from worktree_shield.collectors.base import port_key
from worktree_shield.models import (
    Certainty,
    Confidence,
    Finding,
    Observation,
    ResourceKind,
    Severity,
    Status,
)
from worktree_shield.overlap import Overlap, overlap
from worktree_shield.rules.common import VERIFY, evidence, plain, plural, port_of
from worktree_shield.rules.engine import Context, Rule, confidence_for, status_for

NOT_LOOKED_AT = "Running processes were not looked at"
_WHY_NOT = "The scan ran without the runtime observation (--no-runtime or include_runtime = false)."


def _ports_in_use(context: Context) -> Iterator[Finding]:
    if context.snapshot.runtime is None:
        yield plain(
            "WTS-PORT-002",
            Status.NOT_TESTED,
            NOT_LOOKED_AT,
            _WHY_NOT,
        )
        return
    level = context.policy.shared_host_ports
    found = False
    for collision in context.collisions:
        if (
            collision.kind is not ResourceKind.LISTEN_PORT
            or collision.certainty is not Certainty.CONFIRMED
        ):
            continue
        found = True
        running = [c for c in collision.claims if c.observation is Observation.RUNTIME]
        holders = ", ".join(dict.fromkeys(c.detail for c in running))
        waiting = [c for c in collision.claims if c.worktree not in {r.worktree for r in running}]
        yield Finding(
            "WTS-PORT-002",
            status_for(level, Certainty.CONFIRMED),
            Severity.HIGH,
            Confidence.HIGH,
            f"Port {port_of(collision.key)} is in use by a server running in another worktree",
            f"{holders}; {plural(len({c.worktree for c in waiting}), 'other worktree')} "
            "configure the same port, so their server cannot start while it runs.",
            resource_key=collision.key,
            certainty=Certainty.CONFIRMED,
            worktrees=collision.worktrees,
            sources=tuple(c.source for c in collision.claims),
            evidence=evidence(collision.claims),
            recommended_action="Stop the running server first, or start this worktree's "
            "server on another port.",
            verify_command=VERIFY,
            limitations=("The running processes were looked at once, at the time of the scan.",),
        )
    static = [
        c
        for c in context.snapshot.claims
        if c.kind is ResourceKind.LISTEN_PORT and c.observation is Observation.STATIC
    ]
    for listener in context.snapshot.runtime.unattributed:
        key = port_key(listener.address, listener.port, protocol=listener.protocol)
        matches = [(c, overlap(ResourceKind.LISTEN_PORT, key, c.key)) for c in static]
        blocked = [c for c, result in matches if result is not Overlap.NONE]
        if not blocked:
            continue
        found = True
        certain = any(result is Overlap.SAME for _, result in matches)
        certainty = Certainty.CONFIRMED if certain else Certainty.POSSIBLE
        owner = listener.process or "a process"
        if listener.pid is not None:
            owner += f" (pid {listener.pid})"
        worktrees = tuple(dict.fromkeys(c.worktree for c in blocked))
        yield Finding(
            "WTS-PORT-002",
            status_for(level, certainty),
            Severity.HIGH,
            confidence_for(certainty),
            f"Port {listener.port} is already in use",
            f"{owner} listens on it ({listener.note}); {plural(len(worktrees), 'worktree')} "
            "configure this port, so their server cannot start while it does.",
            resource_key=key,
            certainty=certainty,
            worktrees=worktrees,
            sources=tuple(c.source for c in blocked),
            evidence=evidence(blocked),
            recommended_action="Stop that process if it is a leftover dev server, or give "
            "the worktrees another port.",
            verify_command=VERIFY,
            limitations=("The running processes were looked at once, at the time of the scan.",),
        )
    if not found:
        yield plain(
            "WTS-PORT-002",
            Status.PASS,
            "No configured port is in use by another worktree or process",
            "Every port the worktrees configure was free, as far as the runtime view shows.",
        )


def _runtime_view(context: Context) -> Iterator[Finding]:
    runtime = context.snapshot.runtime
    if runtime is None:
        yield plain(
            "WTS-RUNTIME-001",
            Status.NOT_TESTED,
            NOT_LOOKED_AT,
            _WHY_NOT,
        )
        return
    if runtime.limitations:
        yield Finding(
            "WTS-RUNTIME-001",
            Status.UNKNOWN,
            Severity.LOW,
            Confidence.MEDIUM,
            "Some running processes could not be tied to a worktree",
            "The runtime view is incomplete: " + "; ".join(runtime.limitations) + ".",
            recommended_action="Collisions with processes outside this view cannot be ruled "
            "out; the static findings still apply.",
            limitations=tuple(runtime.limitations),
        )
        return
    yield plain(
        "WTS-RUNTIME-001",
        Status.PASS,
        "Every listening process was visible",
        "No limitation of the runtime view was found.",
    )


RULES = (
    Rule("WTS-PORT-002", "A configured port already held by a running process", _ports_in_use),
    Rule(
        "WTS-RUNTIME-001", "Running processes that could not be tied to a worktree", _runtime_view
    ),
)
