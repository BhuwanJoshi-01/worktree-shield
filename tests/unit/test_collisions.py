"""Claims of different worktrees on the same resource (WTS-008)."""

from __future__ import annotations

from typing import Any

import pytest

from worktree_shield.models import (
    Certainty,
    Observation,
    ResourceClaim,
    ResourceKind,
    SourceRef,
)

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-008")

LISTEN = ResourceKind.LISTEN_PORT


def claim(
    worktree: str,
    key: str,
    kind: ResourceKind = LISTEN,
    *,
    strict: bool | None = None,
    runtime: bool = False,
) -> ResourceClaim:
    return ResourceClaim(
        kind,
        key,
        worktree,
        SourceRef(worktree, ".env.example", 1),
        f"{key} in {worktree}",
        Observation.RUNTIME if runtime else Observation.STATIC,
        strict,
    )


def _find(*claims: ResourceClaim) -> list[Any]:
    from worktree_shield.collisions import find_collisions

    return [(c.kind, c.key, c.certainty, c.worktrees) for c in find_collisions(claims)]


def test_one_worktree_is_no_collision() -> None:
    assert _find(claim("/a", "tcp://*:5173"), claim("/a", "tcp://127.0.0.1:5173")) == []


def test_the_same_port_in_two_worktrees_is_probable() -> None:
    assert _find(claim("/a", "tcp://*:5173"), claim("/b", "tcp://*:5173")) == [
        (LISTEN, "tcp://*:5173", Certainty.PROBABLE, ("/a", "/b"))
    ]


def test_overlapping_addresses_join_one_collision() -> None:
    found = _find(
        claim("/a", "tcp://127.0.0.1:8000"),
        claim("/b", "tcp://0.0.0.0:8000"),
        claim("/c", "tcp://127.0.0.2:8000"),
    )
    assert found == [(LISTEN, "tcp://0.0.0.0:8000", Certainty.PROBABLE, ("/a", "/b", "/c"))]


def test_host_names_make_it_possible() -> None:
    found = _find(claim("/a", "tcp://localhost:8000"), claim("/b", "tcp://127.0.0.1:8000"))
    assert found == [(LISTEN, "tcp://127.0.0.1:8000", Certainty.POSSIBLE, ("/a", "/b"))]


def test_vite_without_strict_port_moves_on() -> None:
    found = _find(
        claim("/a", "tcp://*:5173", strict=False), claim("/b", "tcp://*:5173", strict=False)
    )
    assert found == [(LISTEN, "tcp://*:5173", Certainty.POSSIBLE, ("/a", "/b"))]
    strict = _find(
        claim("/a", "tcp://*:5173", strict=False), claim("/b", "tcp://*:5173", strict=True)
    )
    assert strict[0][2] is Certainty.PROBABLE


def test_a_running_server_confirms_it() -> None:
    found = _find(claim("/a", "tcp://*:3000", runtime=True), claim("/b", "tcp://*:3000"))
    assert found == [(LISTEN, "tcp://*:3000", Certainty.CONFIRMED, ("/a", "/b"))]


def test_client_endpoints_never_collide() -> None:
    client = ResourceKind.CLIENT_ENDPOINT
    assert (
        _find(
            claim("/a", "tcp://localhost:5432", client), claim("/b", "tcp://localhost:5432", client)
        )
        == []
    )


@pytest.mark.parametrize(
    ("kind", "a", "b", "certainty"),
    [
        (
            ResourceKind.DATABASE,
            "db://postgres/localhost:5432/app",
            "db://postgres/127.0.0.1:5432/app",
            Certainty.PROBABLE,
        ),
        (
            ResourceKind.DATABASE,
            "db://postgres/localhost:5432/?",
            "db://postgres/localhost:5432/app",
            Certainty.POSSIBLE,
        ),
        (
            ResourceKind.COMPOSE_PROJECT,
            "compose-project://shop",
            "compose-project://shop",
            Certainty.PROBABLE,
        ),
        (ResourceKind.CONTAINER_NAME, "container://db", "container://db", Certainty.PROBABLE),
        (ResourceKind.VOLUME, "volume://shop_pgdata", "volume://shop_pgdata", Certainty.PROBABLE),
        (
            ResourceKind.ABSOLUTE_PATH,
            "path:///srv/uploads",
            "path:///srv/uploads",
            Certainty.PROBABLE,
        ),
        (ResourceKind.ABSOLUTE_PATH, "path:///srv", "path:///srv/uploads", Certainty.POSSIBLE),
    ],
)
def test_every_kind(kind: ResourceKind, a: str, b: str, certainty: Certainty) -> None:
    (found,) = _find(claim("/a", a, kind), claim("/b", b, kind))
    assert (found[0], found[2]) == (kind, certainty)


def test_reasons_explain_the_consequence() -> None:
    from worktree_shield.collisions import find_collisions

    reasons = {
        c.kind: c.reason
        for c in find_collisions(
            (
                claim("/a", "tcp://*:5173"),
                claim("/b", "tcp://*:5173"),
                claim("/a", "container://db", ResourceKind.CONTAINER_NAME),
                claim("/b", "container://db", ResourceKind.CONTAINER_NAME),
                claim("/a", "tcp://*:4000", strict=False),
                claim("/b", "tcp://*:4000", strict=False),
            )
        )
    }
    assert reasons[LISTEN].startswith("2 worktrees start a server on port")
    assert reasons[ResourceKind.CONTAINER_NAME] == (
        "2 worktrees name a container db; a Docker daemon runs one container of that name, "
        "so starting the second stack replaces or fails on the first"
    )


def test_order_is_stable() -> None:
    claims = [
        claim("/b", "container://x", ResourceKind.CONTAINER_NAME),
        claim("/a", "container://x", ResourceKind.CONTAINER_NAME),
        claim("/a", "tcp://*:2"),
        claim("/b", "tcp://*:2"),
        claim("/a", "tcp://*:1"),
        claim("/b", "tcp://*:1"),
    ]
    keys = [found[1] for found in _find(*claims)]
    assert keys == ["tcp://*:1", "tcp://*:2", "container://x"]
    assert keys == [found[1] for found in _find(*reversed(claims))]
