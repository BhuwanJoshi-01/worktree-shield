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
class Repository:
    """The repository the scan started in, and every worktree that shares its ``.git``.

    ``common_dir`` is the shared Git directory, ``current`` the top of the worktree the
    scan started in (``None`` in a bare repository), ``worktrees`` Git's own list of all
    worktrees attached to ``common_dir``, nothing found by searching the disk.
    """

    common_dir: str
    current: str | None
    bare: bool
    worktrees: tuple[Worktree, ...]


class PolicyLevel(StrEnum):
    """What a kind of shared resource means for ``--strict``.

    ``allow`` reports it as information, ``warn`` as a warning, ``deny`` as a failure,
    which makes ``--strict`` exit with 1.
    """

    ALLOW = "allow"
    WARN = "warn"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class Policy:
    """The effective policy: built-in defaults, then the repository's file, then flags.

    ``allow_ports`` are shared *infrastructure endpoints* that every worktree may
    connect to (one Postgres on 5432 for all of them); they never excuse two processes
    trying to *listen* on the same port. ``source`` is the policy file that was read,
    ``None`` for the defaults alone.
    """

    include_runtime: bool = True
    include_env_files: bool = False
    max_file_bytes: int = 262_144
    shared_host_ports: PolicyLevel = PolicyLevel.DENY
    shared_database: PolicyLevel = PolicyLevel.WARN
    shared_compose_projects: PolicyLevel = PolicyLevel.WARN
    fixed_container_names: PolicyLevel = PolicyLevel.WARN
    shared_absolute_paths: PolicyLevel = PolicyLevel.WARN
    allow_ports: tuple[int, ...] = ()
    allow_paths: tuple[str, ...] = ()
    source: str | None = None


class ResourceKind(StrEnum):
    """What a worktree claims.

    A *listen* port is one its own process binds; a *client endpoint* is a server it
    connects to (a shared Postgres on 5432). Two listeners on one port collide; two
    clients of one server do not, which is why they are different kinds.
    """

    LISTEN_PORT = "listen_port"
    CLIENT_ENDPOINT = "client_endpoint"
    DATABASE = "database"
    COMPOSE_PROJECT = "compose_project"
    CONTAINER_NAME = "container_name"
    VOLUME = "volume"
    ABSOLUTE_PATH = "absolute_path"


class Observation(StrEnum):
    """How a claim was found: read from configuration, or seen on the running system."""

    STATIC = "static"
    RUNTIME = "runtime"


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    """One resource a worktree declares or uses, with where it was found.

    ``key`` identifies the resource (``tcp://*:5173``, ``db://postgres/localhost:5432/app``);
    claims of different worktrees with overlapping keys are collision candidates.
    ``detail`` is what was read, already reduced to safe facts: never a password or the
    value of a variable no rule needs. ``strict`` says whether the program fails when
    the port is taken (``True``) or moves to another one (``False``); ``None`` when the
    configuration does not say.
    """

    kind: ResourceKind
    key: str
    worktree: str
    source: SourceRef
    detail: str
    observation: Observation = Observation.STATIC
    strict: bool | None = None


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """A configuration file that was found but not read, and why (too large, a link
    out of the worktree, not UTF-8…). A skipped file can hide a collision."""

    source: SourceRef
    reason: str


@dataclass(frozen=True, slots=True)
class UnreadableValue:
    """A value that names a resource but could not be read safely, such as a database
    URL whose host is uncertain. ``name`` is the variable or field, never its value."""

    kind: ResourceKind
    source: SourceRef
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class RedactionCount:
    """How many values of one kind (``home_path``, ``secret_value``…) were redacted."""

    kind: str
    count: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything one scan observed and concluded; the input of every renderer.

    ``repository`` is ``None`` when discovery failed (see ``probe_failures``). ``policy``
    is the effective policy, ``claims`` every resource found in the worktrees,
    ``skipped`` the configuration files that could not be read and ``unreadable`` the
    values that name a resource without saying safely which one.
    """

    tool_version: str
    created_at: str
    schema_version: int = SCHEMA_VERSION
    repository: Repository | None = None
    policy: Policy | None = None
    claims: tuple[ResourceClaim, ...] = ()
    skipped: tuple[SkippedFile, ...] = ()
    unreadable: tuple[UnreadableValue, ...] = ()
    probe_failures: tuple[ProbeFailure, ...] = ()
    findings: tuple[Finding, ...] = ()
    redactions: tuple[RedactionCount, ...] = ()
