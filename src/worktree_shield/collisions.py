"""The collision graph: claims of different worktrees on overlapping resources.

Pure: claims in, collisions out. Keys of one kind are joined when any two of them
overlap (:func:`~worktree_shield.overlap.overlap`), so ``0.0.0.0:8000`` links
``127.0.0.1:8000`` and ``127.0.0.2:8000`` into one collision even though those two do
not overlap each other. A group claimed by one worktree only is no collision.

Certainty
    *confirmed* when a running server (a runtime claim) of one worktree certainly holds
    what another worktree's configuration needs; *probable* when the configured
    resources certainly overlap; *possible* when the overlap depends on how a name
    resolves or how a path is used, or when every server involved moves to the next free
    port (Vite without ``strictPort``). Static evidence alone never confirms.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from worktree_shield.models import (
    Certainty,
    Collision,
    Observation,
    ResourceClaim,
    ResourceKind,
)
from worktree_shield.overlap import Overlap, overlap

_KIND_ORDER = {kind: index for index, kind in enumerate(ResourceKind)}


def find_collisions(
    claims: tuple[ResourceClaim, ...] | list[ResourceClaim],
) -> tuple[Collision, ...]:
    """Every collision among ``claims``, ordered by kind and key."""
    by_kind: dict[ResourceKind, list[ResourceClaim]] = defaultdict(list)
    for claim in claims:
        if claim.kind is not ResourceKind.CLIENT_ENDPOINT:
            by_kind[claim.kind].append(claim)
    found: list[Collision] = []
    for kind, members in by_kind.items():
        for group in _groups(kind, members):
            if len({claim.worktree for claim in group}) > 1:
                found.append(_collision(kind, group))
    return tuple(sorted(found, key=lambda c: (_KIND_ORDER[c.kind], c.key)))


def _groups(kind: ResourceKind, claims: list[ResourceClaim]) -> list[list[ResourceClaim]]:
    """Claims joined by overlapping keys (connected components over the keys)."""
    keys = sorted({claim.key for claim in claims})
    parent = {key: key for key in keys}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for a, b in combinations(keys, 2):
        if overlap(kind, a, b) is not Overlap.NONE:
            parent[root(a)] = root(b)
    groups: dict[str, list[ResourceClaim]] = defaultdict(list)
    for claim in claims:
        groups[root(claim.key)].append(claim)
    return list(groups.values())


def _collision(kind: ResourceKind, claims: list[ResourceClaim]) -> Collision:
    pairs = [
        (a, b, overlap(kind, a.key, b.key))
        for a, b in combinations(claims, 2)
        if a.worktree != b.worktree
    ]
    certain = [(a, b) for a, b, result in pairs if result is Overlap.SAME]
    if any(Observation.RUNTIME in (a.observation, b.observation) for a, b in certain):
        certainty = Certainty.CONFIRMED
    elif not certain or (
        kind is ResourceKind.LISTEN_PORT and all(c.strict is False for c in claims)
    ):
        certainty = Certainty.POSSIBLE
    else:
        certainty = Certainty.PROBABLE
    key = min(claim.key for claim in claims)
    worktrees = len({claim.worktree for claim in claims})
    return Collision(kind, key, certainty, _reason(kind, key, worktrees, claims), tuple(claims))


def _reason(kind: ResourceKind, key: str, worktrees: int, claims: list[ResourceClaim]) -> str:
    name = key.split("://", 1)[-1]
    count = f"{worktrees} worktrees"
    if kind is ResourceKind.LISTEN_PORT:
        port = name.rpartition(":")[2]
        reason = f"{count} start a server on port {port}; only one can listen on it at a time"
        if all(claim.strict is False for claim in claims):
            reason += ", but Vite moves to the next free port unless strictPort is set"
        return reason
    if kind is ResourceKind.DATABASE:
        return (
            f"{count} use the same database; migrations, seed data and tests of one "
            "change the data of the other"
        )
    if kind is ResourceKind.COMPOSE_PROJECT:
        return (
            f"{count} have the Compose project name {name}; docker compose up in one "
            "takes over the containers, networks and volumes of the other"
        )
    if kind is ResourceKind.CONTAINER_NAME:
        return (
            f"{count} name a container {name}; a Docker daemon runs one container of that "
            "name, so starting the second stack replaces or fails on the first"
        )
    if kind is ResourceKind.VOLUME:
        return f"{count} mount the Docker volume {name}, so they read and write the same data"
    return f"{count} write to {name} or a directory inside it"
