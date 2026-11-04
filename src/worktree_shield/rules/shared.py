"""Rules for resources configured in more than one worktree (the collision graph)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from worktree_shield.models import (
    Certainty,
    Collision,
    Finding,
    Policy,
    PolicyLevel,
    ResourceKind,
    Severity,
    Status,
)
from worktree_shield.overlap import path_within
from worktree_shield.rules.common import evidence, name_of, plain, port_of, verify_for
from worktree_shield.rules.engine import Context, Rule, confidence_for, status_for


@dataclass(frozen=True, slots=True)
class _Kind:
    rule: str
    title: str
    kind: ResourceKind
    level: Callable[[Policy], PolicyLevel]
    severity: Severity
    summary: Callable[[Collision, int], str]
    action: str | Callable[[Collision], str]
    limitation: str
    nothing: str
    clean: str


def _port_summary(collision: Collision, count: int) -> str:
    return f"Port {port_of(collision.key)} is configured in {count} worktrees"


_ENGINES = {"postgres": "Postgres", "mysql": "MySQL", "redis": "Redis", "mongodb": "MongoDB"}


def _database_summary(collision: Collision, count: int) -> str:
    rest = name_of(collision.key)
    engine, _, target = rest.partition("/")
    if engine == "sqlite":
        return f"The SQLite database {target} is used by {count} worktrees"
    server, _, database = target.rpartition("/")
    label = _ENGINES.get(engine, engine)
    if database == "?":
        return f"An unnamed {label} database on {server} is used by {count} worktrees"
    return f"The {label} database {database} on {server} is used by {count} worktrees"


def _port_action(collision: Collision) -> str:
    port = port_of(collision.key) or 0
    return (
        f"Give each worktree its own port, for example in its own .env (PORT={port} in "
        f"one, PORT={port + 1} in the other), or run one server at a time."
    )


KINDS = (
    _Kind(
        "WTS-PORT-001",
        "A listen port configured in more than one worktree",
        ResourceKind.LISTEN_PORT,
        lambda p: p.shared_host_ports,
        Severity.HIGH,
        _port_summary,
        _port_action,
        "The servers collide only when both run at the same time on this host.",
        "No worktree configures a port to listen on",
        "No port is configured in more than one worktree",
    ),
    _Kind(
        "WTS-DB-001",
        "A database used by more than one worktree",
        ResourceKind.DATABASE,
        lambda p: p.shared_database,
        Severity.HIGH,
        _database_summary,
        "Give each worktree its own database name in its .env (app_dev_login, "
        "app_dev_billing), or allow the server's port in [allow] ports if sharing it is "
        "intended.",
        "Sharing is harmless when the worktrees only read from the database.",
        "No worktree configures a database",
        "No database is used by more than one worktree",
    ),
    _Kind(
        "WTS-DOCKER-001",
        "A Compose project name shared by worktrees",
        ResourceKind.COMPOSE_PROJECT,
        lambda p: p.shared_compose_projects,
        Severity.MEDIUM,
        lambda c, n: f"The Compose project {name_of(c.key)} is used by {n} worktrees",
        "Set COMPOSE_PROJECT_NAME in each worktree's .env, or remove name: from the "
        "compose file so each worktree's directory name is used.",
        "The stacks collide only when they run on the same Docker daemon.",
        "No Compose file was found",
        "Every worktree has its own Compose project name",
    ),
    _Kind(
        "WTS-DOCKER-002",
        "A fixed container name set in more than one worktree",
        ResourceKind.CONTAINER_NAME,
        lambda p: p.fixed_container_names,
        Severity.MEDIUM,
        lambda c, n: f"The container name {name_of(c.key)} is set in {n} worktrees",
        "Remove container_name so Compose names containers after the project, or build "
        "it from the project name: container_name: ${COMPOSE_PROJECT_NAME}-db.",
        "The containers collide only when both stacks run on the same Docker daemon.",
        "No Compose service sets a container name",
        "No container name is set in more than one worktree",
    ),
    _Kind(
        "WTS-DOCKER-003",
        "A Docker volume mounted in more than one worktree",
        ResourceKind.VOLUME,
        lambda p: p.shared_compose_projects,
        Severity.MEDIUM,
        lambda c, n: f"The Docker volume {name_of(c.key)} is mounted in {n} worktrees",
        "Let Compose prefix the volume with the project name (drop its name: or "
        "external:), or mark it external on purpose if the data is meant to be shared.",
        "The data is shared only on the same Docker daemon.",
        "No Compose service mounts a named volume",
        "No Docker volume is mounted in more than one worktree",
    ),
    _Kind(
        "WTS-PATH-001",
        "An absolute path more than one worktree writes to",
        ResourceKind.ABSOLUTE_PATH,
        lambda p: p.shared_absolute_paths,
        Severity.MEDIUM,
        lambda c, n: f"{n} worktrees write to {name_of(c.key)}",
        "Point each worktree at its own directory (a relative path, or one per worktree "
        "in its .env), or list the path in [allow] paths if it is meant to be shared.",
        "Whether both write there depends on how the path is used.",
        "No worktree configures an absolute path",
        "No absolute path is used by more than one worktree",
    ),
)


def _allowed(kind: ResourceKind, collision: Collision, policy: Policy) -> str | None:
    """Why the policy allows this collision, or ``None``."""
    if kind is ResourceKind.DATABASE and policy.allow_ports:
        ports = {port_of(claim.key) for claim in collision.claims}
        if ports and ports <= set(policy.allow_ports):
            return "[allow] ports lists the server's port as shared infrastructure"
    if kind is ResourceKind.ABSOLUTE_PATH:
        for directory in policy.allow_paths:
            if path_within(collision.key, directory):
                return f"[allow] paths lists {directory}"
    return None


def _action(spec: _Kind, collision: Collision) -> str:
    return spec.action if isinstance(spec.action, str) else spec.action(collision)


def _check(spec: _Kind) -> Callable[[Context], Iterator[Finding]]:
    def check(context: Context) -> Iterator[Finding]:
        if not any(c.kind is spec.kind for c in context.snapshot.claims):
            reason = "Nothing of this kind was found in the configuration."
            yield plain(spec.rule, Status.NOT_APPLICABLE, spec.nothing, reason)
            return
        collisions = [
            c
            for c in context.collisions
            if c.kind is spec.kind
            and not (spec.kind is ResourceKind.LISTEN_PORT and c.certainty is Certainty.CONFIRMED)
        ]
        if not collisions:
            yield plain(spec.rule, Status.PASS, spec.clean, "Each worktree uses its own.")
            return
        projects = {
            name_of(c.key) for c in context.collisions if c.kind is ResourceKind.COMPOSE_PROJECT
        }
        for collision in collisions:
            allowed = _allowed(spec.kind, collision, context.policy)
            level = PolicyLevel.ALLOW if allowed else spec.level(context.policy)
            reason = collision.reason + "."
            if allowed:
                reason += f" {allowed[0].upper()}{allowed[1:]}; the policy allows this."
            elif level is PolicyLevel.ALLOW:
                reason += " The policy allows this."
            caused_by = None
            if spec.kind is ResourceKind.VOLUME and any(
                name_of(collision.key).startswith(f"{project}_") for project in projects
            ):
                caused_by = "WTS-DOCKER-001"
            count = len(collision.worktrees)
            yield Finding(
                spec.rule,
                status_for(level, collision.certainty),
                spec.severity,
                confidence_for(collision.certainty),
                spec.summary(collision, count),
                reason,
                resource_key=collision.key,
                certainty=collision.certainty,
                worktrees=collision.worktrees,
                sources=tuple(claim.source for claim in collision.claims),
                evidence=evidence(collision.claims),
                recommended_action=_action(spec, collision),
                verify_command=verify_for(collision.claims, context.policy),
                limitations=(spec.limitation,),
                caused_by=caused_by,
            )

    return check


RULES = tuple(Rule(spec.rule, spec.title, _check(spec)) for spec in KINDS)
