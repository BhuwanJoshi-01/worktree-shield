"""Rules about what the scan could and could not see, and about the policy itself."""

from __future__ import annotations

from collections.abc import Iterator

from worktree_shield.collectors.envfiles import NOT_READ
from worktree_shield.models import (
    Confidence,
    Evidence,
    Finding,
    Observation,
    ResourceKind,
    Severity,
    Status,
)
from worktree_shield.rules.common import evidence, plain, plural, port_of, where
from worktree_shield.rules.engine import Context, Rule


def _unreadable_databases(context: Context) -> Iterator[Finding]:
    values = [v for v in context.snapshot.unreadable if v.kind is ResourceKind.DATABASE]
    for value in values:
        yield Finding(
            "WTS-DB-002",
            Status.UNKNOWN,
            Severity.MEDIUM,
            Confidence.MEDIUM,
            f"{value.name} in {where(value.source)} names a database that could not be identified",
            f"The URL {value.reason}. A collision on this database can be neither "
            "confirmed nor ruled out; its value is not shown.",
            worktrees=(value.source.worktree,),
            sources=(value.source,),
            recommended_action="Percent-encode special characters in the password (/ is %2F, "
            "# is %23, ? is %3F) and spell the host out.",
            verify_command="worktree-shield resources",
        )
    if values:
        return
    if any(c.kind is ResourceKind.DATABASE for c in context.snapshot.claims):
        yield plain(
            "WTS-DB-002",
            Status.PASS,
            "Every database URL could be identified",
            "No database URL was refused.",
        )
    else:
        yield plain(
            "WTS-DB-002",
            Status.NOT_APPLICABLE,
            "No database URL was found",
            "Nothing of this kind was found in the configuration.",
        )


def _unread_configuration(context: Context) -> Iterator[Finding]:
    skipped = [s for s in context.snapshot.skipped if s.reason != NOT_READ]
    values = [v for v in context.snapshot.unreadable if v.kind is not ResourceKind.DATABASE]
    items = [Evidence(where(s.source), s.source.worktree, s.reason) for s in skipped]
    items += [Evidence(where(v.source), v.source.worktree, f"{v.name} {v.reason}") for v in values]
    if not items:
        yield plain(
            "WTS-CONFIG-001",
            Status.PASS,
            "Every configuration file found was read",
            "No file was refused and every value could be identified.",
        )
        return
    worktrees = tuple(dict.fromkeys(item.key for item in items))
    yield Finding(
        "WTS-CONFIG-001",
        Status.UNKNOWN,
        Severity.LOW,
        Confidence.MEDIUM,
        f"{plural(len(items), 'configuration item')} could not be read",
        "A file that was not read, or a value that could not be identified, can hide a collision.",
        worktrees=worktrees,
        sources=tuple(s.source for s in skipped) + tuple(v.source for v in values),
        evidence=tuple(items),
        recommended_action="Fix the files listed (or raise scan.max_file_bytes for large "
        "ones), then scan again.",
        verify_command="worktree-shield resources",
    )


def _env_files(context: Context) -> Iterator[Finding]:
    unread = [s for s in context.snapshot.skipped if s.reason == NOT_READ]
    if unread:
        worktrees = tuple(dict.fromkeys(s.source.worktree for s in unread))
        yield Finding(
            "WTS-ENV-001",
            Status.UNKNOWN,
            Severity.LOW,
            Confidence.MEDIUM,
            f"{plural(len(unread), '.env file')} {'was' if len(unread) == 1 else 'were'} not read",
            "What runs may differ from what was read: a .env can set another port or "
            "database than the templates, which would make a finding wrong or miss one.",
            worktrees=worktrees,
            sources=tuple(s.source for s in unread),
            evidence=tuple(
                Evidence(where(s.source), s.source.worktree, "not read") for s in unread
            ),
            recommended_action="Scan with --include-env (or include_env_files = true); only "
            "ports, database servers and paths are kept from them.",
            verify_command="worktree-shield scan --include-env",
        )
    elif context.policy.include_env_files:
        yield plain(
            "WTS-ENV-001",
            Status.PASS,
            ".env files were read",
            "The scan included .env and .env.local.",
        )
    else:
        yield plain(
            "WTS-ENV-001",
            Status.NOT_APPLICABLE,
            "No .env files were found",
            "No worktree has a .env or .env.local.",
        )


def _prunable(context: Context) -> Iterator[Finding]:
    repository = context.snapshot.repository
    gone = [w for w in repository.worktrees if w.prunable is not None] if repository else []
    for worktree in gone:
        yield Finding(
            "WTS-GIT-002",
            Status.WARN,
            Severity.INFO,
            Confidence.HIGH,
            f"The worktree {worktree.path} is listed by Git but its directory is gone",
            "Git keeps the record until it is pruned; nothing there can collide, and it was "
            "not scanned." + (f" Git says: {worktree.prunable}." if worktree.prunable else ""),
            worktrees=(worktree.path,),
            recommended_action="If it is gone for good, git worktree prune removes the record; "
            "worktree-shield never prunes.",
            verify_command="git worktree list",
        )
    if not gone:
        yield plain(
            "WTS-GIT-002", Status.PASS, "Every listed worktree exists", "No worktree is prunable."
        )


def _policy_contradictions(context: Context) -> Iterator[Finding]:
    policy = context.policy
    if not policy.allow_ports and not policy.allow_paths:
        yield plain(
            "WTS-POLICY-001",
            Status.NOT_APPLICABLE,
            "The policy allows nothing explicitly",
            "There are no [allow] entries to check.",
        )
        return
    listening = [
        c
        for c in context.snapshot.claims
        if c.kind is ResourceKind.LISTEN_PORT and c.observation is Observation.STATIC
    ]
    found = False
    for port in policy.allow_ports:
        claims = [c for c in listening if port_of(c.key) == port]
        if not claims:
            continue
        found = True
        where_set = f" in {policy.source}" if policy.source else ""
        yield Finding(
            "WTS-POLICY-001",
            Status.WARN,
            Severity.LOW,
            Confidence.HIGH,
            f"[allow] ports lists {port}, which the worktrees listen on",
            "[allow] ports covers servers the worktrees connect to, such as one shared "
            "database; it never lets two servers listen on one port, so WTS-PORT-001 still "
            "applies to it.",
            worktrees=tuple(dict.fromkeys(c.worktree for c in claims)),
            sources=tuple(c.source for c in claims),
            evidence=evidence(claims),
            recommended_action=f"Remove {port} from [allow] ports{where_set}, or give each "
            "worktree its own port.",
            verify_command="worktree-shield policy",
        )
    if not found:
        yield plain(
            "WTS-POLICY-001",
            Status.PASS,
            "The policy matches the configuration",
            "No [allow] entry contradicts what the worktrees configure.",
        )


RULES = (
    Rule("WTS-DB-002", "A database URL that could not be identified safely", _unreadable_databases),
    Rule("WTS-CONFIG-001", "Configuration that could not be read", _unread_configuration),
    Rule("WTS-ENV-001", ".env files the scan did not read", _env_files),
    Rule("WTS-GIT-002", "A worktree Git lists whose directory is gone", _prunable),
    Rule(
        "WTS-POLICY-001", "An [allow] entry the configuration contradicts", _policy_contradictions
    ),
)
