"""Properties of overlap() and the collision graph that must hold for any input."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from worktree_shield.collisions import find_collisions
from worktree_shield.models import Certainty, ResourceClaim, ResourceKind, SourceRef
from worktree_shield.overlap import Overlap, overlap

HOSTS = st.sampled_from(
    ["*", "0.0.0.0", "[::]", "127.0.0.1", "127.0.0.2", "[::1]", "localhost", "dev.local"]
)
PORTS = st.integers(min_value=1, max_value=4)
PORT_KEYS = st.builds(
    lambda p, h, n: f"{p}://{h}:{n}", st.sampled_from(["tcp", "udp"]), HOSTS, PORTS
)
DB_KEYS = st.builds(
    lambda e, s, d: f"db://{e}/{s}:5432/{d}",
    st.sampled_from(["postgres", "mysql"]),
    st.sampled_from(["localhost", "127.0.0.1", "[::1]", "local", "db.internal", "unix:/run/pg"]),
    st.sampled_from(["app", "other", "?"]),
)
PATH_KEYS = st.builds(
    lambda parts: "path:///" + "/".join(parts),
    st.lists(st.sampled_from(["srv", "cache", "a", "..", "."]), min_size=1, max_size=4),
)
KINDS = st.sampled_from(
    [
        (ResourceKind.LISTEN_PORT, PORT_KEYS),
        (ResourceKind.DATABASE, DB_KEYS),
        (ResourceKind.ABSOLUTE_PATH, PATH_KEYS),
    ]
)


@given(st.data())
def test_overlap_is_symmetric_and_reflexive(data: st.DataObject) -> None:
    kind, keys = data.draw(KINDS)
    a, b = data.draw(keys), data.draw(keys)
    assert overlap(kind, a, b) is overlap(kind, b, a)
    # A key equals itself, except a database left unnamed: Postgres then uses the user
    # name, which was dropped, so two such claims only possibly name one database.
    unnamed = kind is ResourceKind.DATABASE and a.endswith("/?")
    assert overlap(kind, a, a) is (Overlap.POSSIBLE if unnamed else Overlap.SAME)


@given(st.lists(st.tuples(st.sampled_from(["/w/a", "/w/b", "/w/c"]), PORT_KEYS), max_size=8))
def test_collisions_need_two_worktrees_and_static_claims_never_confirm(
    claims: list[tuple[str, str]],
) -> None:
    built = [
        ResourceClaim(ResourceKind.LISTEN_PORT, key, worktree, SourceRef(worktree, "f", 1), "d")
        for worktree, key in claims
    ]
    for collision in find_collisions(built):
        assert len(collision.worktrees) >= 2
        assert collision.certainty is not Certainty.CONFIRMED
        assert collision.key in {claim.key for claim in collision.claims}


@given(st.lists(st.tuples(st.sampled_from(["/w/a", "/w/b"]), PORT_KEYS), max_size=8))
def test_the_result_does_not_depend_on_the_order_of_claims(claims: list[tuple[str, str]]) -> None:
    built = [
        ResourceClaim(ResourceKind.LISTEN_PORT, key, worktree, SourceRef(worktree, "f", 1), "d")
        for worktree, key in claims
    ]

    def summary(found: tuple[object, ...]) -> list[tuple[str, str, frozenset[str]]]:
        return [(c.key, c.certainty.value, frozenset(c.worktrees)) for c in found]  # type: ignore[attr-defined]

    assert summary(find_collisions(built)) == summary(find_collisions(list(reversed(built))))
