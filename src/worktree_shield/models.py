"""Typed facts and findings shared by collectors, rules and renderers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

SCHEMA_VERSION = 1
"""Version of the snapshot/JSON report layout; bumped only for incompatible changes."""

FINDING_ID = re.compile(r"WTS-[A-Z]+-[0-9]{3}")
"""Finding codes are part of the public contract: ``WTS-<AREA>-<NNN>``, e.g. ``WTS-PORT-001``."""


class Status(StrEnum):
    """Outcome of one check.

    Only ``PASS`` means that a check ran and found nothing shared. A check that could not
    run is ``UNKNOWN``; one that was deliberately skipped (runtime inspection nobody asked
    for) is ``NOT_TESTED``; one that does not apply to this repository is
    ``NOT_APPLICABLE``.
    """

    PASS = "pass"  # noqa: S105 - a status name, not a password
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    NOT_TESTED = "not_tested"


class Severity(StrEnum):
    """How much a finding matters, independent of certainty."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Confidence(StrEnum):
    """How well the evidence supports a finding."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Certainty(StrEnum):
    """How sure a collision is, from the kind of evidence behind it.

    Static evidence (two configs declare the same port) is ``PROBABLE`` at most: it only
    matters if both run at once on the same host. ``CONFIRMED`` needs a running process
    attributed to a worktree by its working directory. ``POSSIBLE`` covers looser matches
    (``localhost`` against ``127.0.0.1``); ``UNKNOWN`` means it could not be decided.
    """

    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    POSSIBLE = "possible"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where a claim comes from: a file (relative to its worktree) and, if known, a line."""

    worktree: str
    path: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    """One observed fact that a finding relies on; ``value`` is ``None`` when missing."""

    source: str
    key: str
    value: str | None


@dataclass(frozen=True, slots=True)
class Finding:
    """A diagnosis with everything a user needs to judge and verify it.

    ``resource_key`` is the normalised shared resource (``tcp://*:5173``,
    ``db://postgres/localhost:5432/app_dev``…), ``worktrees`` the worktrees involved and
    ``sources`` where each claim was found. ``certainty`` applies to collisions.
    ``verify_command`` re-checks the result after acting on ``recommended_action``;
    ``caused_by`` names the finding this one follows from, so reports show one root
    cause instead of a cascade.
    """

    id: str
    status: Status
    severity: Severity
    confidence: Confidence
    summary: str
    reason: str
    resource_key: str | None = None
    certainty: Certainty | None = None
    worktrees: tuple[str, ...] = ()
    sources: tuple[SourceRef, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    recommended_action: str | None = None
    verify_command: str | None = None
    limitations: tuple[str, ...] = ()
    caused_by: str | None = None

    def __post_init__(self) -> None:
        if not FINDING_ID.fullmatch(self.id):
            raise ValueError(f"finding id {self.id!r} does not match WTS-<AREA>-<NNN>")
        if self.caused_by is not None and not FINDING_ID.fullmatch(self.caused_by):
            raise ValueError(f"caused_by {self.caused_by!r} does not match WTS-<AREA>-<NNN>")
        if not self.summary.strip():
            raise ValueError(f"finding {self.id} has an empty summary")


class FailureKind(StrEnum):
    """Why a probe produced no usable facts."""

    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    NONZERO_EXIT = "nonzero_exit"
    MALFORMED_OUTPUT = "malformed_output"
    OS_ERROR = "os_error"
    PROBE_ERROR = "probe_error"
    """The probe ran, but reported that part of its own work failed."""


@dataclass(frozen=True, slots=True)
class ProbeFailure:
    """A probe that could not deliver its facts; collectors return these instead of raising."""

    probe: str
    kind: FailureKind
    detail: str


def utc_timestamp() -> str:
    """Current time as an ISO 8601 UTC string with second precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class Worktree:
    """One entry of ``git worktree list --porcelain``.

    ``branch`` is the full ref (``refs/heads/feature``) or ``None`` when detached or
    bare. ``locked`` and ``prunable`` carry Git's reason, ``""`` when it gave none and
    ``None`` when the flag is not set. A prunable worktree is listed but its directory
    is gone; it is reported, never pruned.
    """

    path: str
    head: str | None = None
    branch: str | None = None
    bare: bool = False
    detached: bool = False
    locked: str | None = None
    prunable: str | None = None


@dataclass(frozen=True, slots=True)
class RedactionCount:
    """How many values of one kind (``home_path``, ``secret_value``…) were redacted."""

    kind: str
    count: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything one scan observed and concluded; the input of every renderer.

    Worktree, claim and runtime facts join this record as their collectors are added.
    """

    tool_version: str
    created_at: str
    schema_version: int = SCHEMA_VERSION
    probe_failures: tuple[ProbeFailure, ...] = ()
    findings: tuple[Finding, ...] = ()
    redactions: tuple[RedactionCount, ...] = ()
