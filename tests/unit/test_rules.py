"""The WTS rules: collisions, runtime and context turned into findings (WTS-010)."""

from __future__ import annotations

from typing import Any

import pytest

from worktree_shield.models import (
    Finding,
    Listener,
    Observation,
    Policy,
    PolicyLevel,
    Repository,
    ResourceClaim,
    ResourceKind,
    RuntimeFacts,
    SkippedFile,
    Snapshot,
    SourceRef,
    Status,
    UnreadableValue,
    Worktree,
)

A, B = "/src/app", "/src/app-login"
REPOSITORY = Repository("/src/app/.git", A, False, (Worktree(A), Worktree(B)))


def claim(
    worktree: str, kind: ResourceKind, key: str, *, runtime: bool = False, strict: Any = None
) -> ResourceClaim:
    path = "pid 7" if runtime else ".env.example"
    return ResourceClaim(
        kind,
        key,
        worktree,
        SourceRef(worktree, path, None if runtime else 3),
        f"{key} in {worktree}",
        Observation.RUNTIME if runtime else Observation.STATIC,
        strict,
    )


def diagnose(
    *claims: ResourceClaim, policy: Policy | None = None, **extra: Any
) -> dict[str, list[Finding]]:
    from worktree_shield.rules.catalog import builtin_rules
    from worktree_shield.rules.engine import evaluate

    snapshot = Snapshot(
        "0.1.0",
        "t",
        repository=extra.pop("repository", REPOSITORY),
        policy=policy or Policy(),
        claims=claims,
        runtime=extra.pop("runtime", RuntimeFacts()),
        **extra,
    )
    found: dict[str, list[Finding]] = {}
    for finding in evaluate(snapshot, builtin_rules()):
        found.setdefault(finding.id, []).append(finding)
    return found


def status(found: dict[str, list[Finding]], rule: str) -> list[Status]:
    return [f.status for f in found[rule]]


PORT = ResourceKind.LISTEN_PORT


def test_a_clean_repository_passes_or_does_not_apply() -> None:
    found = diagnose(claim(A, PORT, "tcp://*:5173"), claim(B, PORT, "tcp://*:5174"))
    assert status(found, "WTS-PORT-001") == [Status.PASS]
    assert status(found, "WTS-DB-001") == [Status.NOT_APPLICABLE]
    assert status(found, "WTS-DOCKER-001") == [Status.NOT_APPLICABLE]
    assert status(found, "WTS-PORT-002") == [Status.PASS]
    assert status(found, "WTS-GIT-002") == [Status.PASS]


def test_a_shared_port_fails_under_the_default_policy() -> None:
    found = diagnose(claim(A, PORT, "tcp://*:5173"), claim(B, PORT, "tcp://*:5173"))
    (finding,) = found["WTS-PORT-001"]
    assert finding.status is Status.FAIL
    assert finding.summary == "Port 5173 is configured in 2 worktrees"
    assert finding.certainty is not None
    assert finding.certainty.value == "probable"
    assert finding.worktrees == (A, B)
    assert [s.path for s in finding.sources] == [".env.example", ".env.example"]
    assert finding.recommended_action is not None
    assert finding.verify_command == "worktree-shield scan --strict"


def test_policy_levels_set_the_status() -> None:
    shared = (claim(A, PORT, "tcp://*:5173"), claim(B, PORT, "tcp://*:5173"))
    warn = diagnose(*shared, policy=Policy(shared_host_ports=PolicyLevel.WARN))
    assert status(warn, "WTS-PORT-001") == [Status.WARN]
    allow = diagnose(*shared, policy=Policy(shared_host_ports=PolicyLevel.ALLOW))
    assert status(allow, "WTS-PORT-001") == [Status.PASS]
    assert allow["WTS-PORT-001"][0].reason.endswith("The policy allows this.")


def test_a_possible_collision_only_warns_even_when_denied() -> None:
    found = diagnose(
        claim(A, PORT, "tcp://*:5173", strict=False), claim(B, PORT, "tcp://*:5173", strict=False)
    )
    assert status(found, "WTS-PORT-001") == [Status.WARN]


def test_a_running_server_is_a_current_blocker() -> None:
    found = diagnose(claim(A, PORT, "tcp://*:3000", runtime=True), claim(B, PORT, "tcp://*:3000"))
    assert status(found, "WTS-PORT-001") == [Status.PASS]
    (blocker,) = found["WTS-PORT-002"]
    assert blocker.status is Status.FAIL
    assert blocker.summary == "Port 3000 is in use by a server running in another worktree"


def test_a_configured_port_held_outside_the_worktrees() -> None:
    runtime = RuntimeFacts(
        (Listener("tcp", "0.0.0.0", 5432, None, None, "owned by a process of another user"),)
    )
    found = diagnose(claim(A, PORT, "tcp://*:5432"), runtime=runtime)
    (blocker,) = found["WTS-PORT-002"]
    assert blocker.status is Status.FAIL
    assert blocker.summary == "Port 5432 is already in use"
    assert blocker.reason.startswith("A process of another user listens on it;")


def test_without_runtime_the_runtime_rules_are_not_tested() -> None:
    found = diagnose(claim(A, PORT, "tcp://*:1"), runtime=None)
    assert status(found, "WTS-PORT-002") == [Status.NOT_TESTED]
    assert status(found, "WTS-RUNTIME-001") == [Status.NOT_TESTED]


def test_runtime_limits_are_unknown() -> None:
    found = diagnose(runtime=RuntimeFacts(limitations=("only your own processes are visible",)))
    assert status(found, "WTS-RUNTIME-001") == [Status.UNKNOWN]


@pytest.mark.parametrize(
    ("kind", "key", "rule", "summary"),
    [
        (
            ResourceKind.DATABASE,
            "db://postgres/localhost:5432/app_dev",
            "WTS-DB-001",
            "The Postgres database app_dev on localhost:5432 is used by 2 worktrees",
        ),
        (
            ResourceKind.COMPOSE_PROJECT,
            "compose-project://shop",
            "WTS-DOCKER-001",
            "The Compose project shop is used by 2 worktrees",
        ),
        (
            ResourceKind.CONTAINER_NAME,
            "container://shop-db",
            "WTS-DOCKER-002",
            "The container name shop-db is set in 2 worktrees",
        ),
        (
            ResourceKind.VOLUME,
            "volume://pgdata",
            "WTS-DOCKER-003",
            "The Docker volume pgdata is mounted in 2 worktrees",
        ),
        (
            ResourceKind.ABSOLUTE_PATH,
            "path:///srv/uploads",
            "WTS-PATH-001",
            "2 worktrees write to /srv/uploads",
        ),
    ],
)
def test_every_kind_has_its_rule(kind: ResourceKind, key: str, rule: str, summary: str) -> None:
    (finding,) = diagnose(claim(A, kind, key), claim(B, kind, key))[rule]
    assert finding.summary == summary
    assert finding.status is Status.WARN  # all of these warn by default


def test_volumes_of_a_shared_project_follow_from_it() -> None:
    found = diagnose(
        claim(A, ResourceKind.COMPOSE_PROJECT, "compose-project://shop"),
        claim(B, ResourceKind.COMPOSE_PROJECT, "compose-project://shop"),
        claim(A, ResourceKind.VOLUME, "volume://shop_pgdata"),
        claim(B, ResourceKind.VOLUME, "volume://shop_pgdata"),
    )
    assert found["WTS-DOCKER-003"][0].caused_by == "WTS-DOCKER-001"


def test_allowed_infrastructure_and_paths() -> None:
    policy = Policy(allow_ports=(5432,), allow_paths=("/srv/cache",))
    found = diagnose(
        claim(A, ResourceKind.DATABASE, "db://postgres/localhost:5432/app"),
        claim(B, ResourceKind.DATABASE, "db://postgres/localhost:5432/app"),
        claim(A, ResourceKind.ABSOLUTE_PATH, "path:///srv/cache/images"),
        claim(B, ResourceKind.ABSOLUTE_PATH, "path:///srv/cache/images"),
        policy=policy,
    )
    assert status(found, "WTS-DB-001") == [Status.PASS]
    assert status(found, "WTS-PATH-001") == [Status.PASS]
    assert status(found, "WTS-POLICY-001") == [Status.PASS]


def test_allowing_a_port_the_worktrees_listen_on_is_a_contradiction() -> None:
    found = diagnose(
        claim(A, PORT, "tcp://*:5173"),
        claim(B, PORT, "tcp://*:5173"),
        policy=Policy(allow_ports=(5173,), source="/src/app/.worktree-shield.toml"),
    )
    (contradiction,) = found["WTS-POLICY-001"]
    assert contradiction.status is Status.WARN
    assert "5173" in contradiction.summary
    assert status(found, "WTS-PORT-001") == [Status.FAIL]  # allow.ports does not excuse listeners


def test_unreadable_values_and_files() -> None:
    found = diagnose(
        unreadable=(
            UnreadableValue(
                ResourceKind.DATABASE,
                SourceRef(A, ".env", 1),
                "DATABASE_URL",
                "it lists several hosts",
            ),
            UnreadableValue(
                ResourceKind.LISTEN_PORT,
                SourceRef(B, "compose.yaml", 9),
                "services.web.ports[0]",
                "is not a valid port mapping",
            ),
        ),
        skipped=(SkippedFile(SourceRef(A, "package.json", None), "is not valid JSON"),),
    )
    assert status(found, "WTS-DB-002") == [Status.UNKNOWN]
    (config,) = found["WTS-CONFIG-001"]
    assert config.status is Status.UNKNOWN
    assert config.summary == "2 configuration items could not be read"


def test_env_files_left_unread() -> None:
    from worktree_shield.collectors.envfiles import NOT_READ

    skipped = (SkippedFile(SourceRef(A, ".env", None), NOT_READ),)
    found = diagnose(skipped=skipped)
    assert status(found, "WTS-ENV-001") == [Status.UNKNOWN]
    assert status(found, "WTS-CONFIG-001") == [Status.PASS]  # counted once, as ENV-001


def test_prunable_worktrees_are_noted_never_pruned() -> None:
    repository = Repository(
        "/src/app/.git", A, False, (Worktree(A), Worktree("/gone", prunable=""))
    )
    (finding,) = diagnose(repository=repository)["WTS-GIT-002"]
    assert finding.status is Status.WARN
    assert "git worktree prune" in (finding.recommended_action or "")


def test_every_rule_runs_and_ids_are_unique() -> None:
    from worktree_shield.rules.catalog import builtin_rules

    ids = [rule.id for rule in builtin_rules()]
    assert len(ids) == len(set(ids))
    assert set(diagnose()) == set(ids)


@pytest.mark.parametrize(
    ("key", "summary"),
    [
        ("db://sqlite//srv/app.db", "The SQLite database /srv/app.db is used by 2 worktrees"),
        (
            "db://postgres/localhost:5432/?",
            "An unnamed Postgres database on localhost:5432 is used by 2 worktrees",
        ),
    ],
)
def test_database_summaries(key: str, summary: str) -> None:
    db = ResourceKind.DATABASE
    assert diagnose(claim(A, db, key), claim(B, db, key))["WTS-DB-001"][0].summary == summary


def test_git_explains_why_a_worktree_is_prunable() -> None:
    gone = Worktree("/gone", prunable="gitdir file points to non-existent location")
    repository = Repository("/src/app/.git", A, False, (Worktree(A), gone))
    (finding,) = diagnose(repository=repository)["WTS-GIT-002"]
    assert finding.reason.endswith("Git says: gitdir file points to non-existent location.")


def test_a_known_process_outside_the_worktrees_and_a_host_name() -> None:
    runtime = RuntimeFacts(
        (Listener("tcp", "127.0.0.1", 8000, 42, "uvicorn", "it runs outside every worktree"),)
    )
    found = diagnose(claim(A, PORT, "tcp://localhost:8000"), runtime=runtime)
    (blocker,) = found["WTS-PORT-002"]
    assert blocker.reason.startswith(
        "uvicorn (pid 42) listens on it; it runs outside every worktree; 1 worktree configures"
    )
    assert blocker.certainty is not None
    assert blocker.certainty.value == "possible"  # localhost may not be 127.0.0.1
    assert blocker.status is Status.WARN


def test_a_path_outside_every_allowed_one_still_warns() -> None:
    path = ResourceKind.ABSOLUTE_PATH
    found = diagnose(
        claim(A, path, "path:///srv/uploads"),
        claim(B, path, "path:///srv/uploads"),
        policy=Policy(allow_paths=("/tmp/cache", "/srv/other")),  # noqa: S108
    )
    assert status(found, "WTS-PATH-001") == [Status.WARN]


def test_remaining_branches() -> None:
    db = ResourceKind.DATABASE
    shared_db = (
        claim(A, db, "db://postgres/localhost:5432/app"),
        claim(B, db, "db://postgres/localhost:5432/app"),
    )
    assert status(diagnose(*shared_db, policy=Policy(allow_ports=(6379,))), "WTS-DB-001") == [
        Status.WARN
    ]
    assert status(diagnose(policy=Policy(include_env_files=True)), "WTS-ENV-001") == [Status.PASS]
    elsewhere = RuntimeFacts(
        (Listener("tcp", "0.0.0.0", 9999, None, None, "owned by a process of another user"),)
    )
    assert status(diagnose(claim(A, PORT, "tcp://*:1"), runtime=elsewhere), "WTS-PORT-002") == [
        Status.PASS
    ]
