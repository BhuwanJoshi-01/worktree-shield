"""git worktree list --porcelain -z (WTS-001)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.fakes import read_fixture
from worktree_shield.git.porcelain import PorcelainError, parse_worktree_list
from worktree_shield.models import Worktree

SHA = "374137f3fa3fd339f531a62da641af2560a70050"


def test_real_odd_worktrees() -> None:
    worktrees = parse_worktree_list(read_fixture("git", "worktree-list-odd.porcelain"))
    assert worktrees == (
        Worktree("/home/user/src/repo", SHA, "refs/heads/main"),
        Worktree("/home/user/src/detached", SHA, detached=True, locked="on a USB disk"),
        Worktree(
            "/home/user/src/gone",
            SHA,
            "refs/heads/feature-d",
            prunable="gitdir file points to non-existent location",
        ),
        Worktree("/home/user/src/new\nline", SHA, "refs/heads/feature-c"),
        Worktree("/home/user/src/with space", SHA, "refs/heads/feature-a"),
        Worktree("/home/user/src/ünïcode", SHA, "refs/heads/feature-b"),
    )


def test_real_bare_repository() -> None:
    worktrees = parse_worktree_list(read_fixture("git", "worktree-list-bare.porcelain"))
    assert worktrees == (
        Worktree("/home/user/src/bare.git", bare=True),
        Worktree("/home/user/src/from-bare", SHA, "refs/heads/main"),
    )


def test_flags_without_a_reason() -> None:
    text = f"worktree /a\0HEAD {SHA}\0detached\0locked\0prunable\0\0"
    assert parse_worktree_list(text) == (
        Worktree("/a", SHA, detached=True, locked="", prunable=""),
    )


def test_unknown_attributes_are_skipped() -> None:
    text = f"worktree /a\0HEAD {SHA}\0branch refs/heads/x\0future-flag yes\0\0"
    assert parse_worktree_list(text) == (Worktree("/a", SHA, "refs/heads/x"),)


def test_empty_output_lists_nothing() -> None:
    assert parse_worktree_list("") == ()


@pytest.mark.parametrize("text", ["HEAD abc\0\0", "worktree\0\0", "/just/a/path\n"])
def test_records_must_start_with_a_worktree_path(text: str) -> None:
    with pytest.raises(PorcelainError):
        parse_worktree_list(text)


_paths = st.text(
    alphabet=st.characters(blacklist_characters="\0", blacklist_categories=("Cs",)), min_size=1
)


@given(st.lists(_paths, min_size=1, max_size=5))
def test_any_path_without_nul_round_trips(paths: list[str]) -> None:
    text = "".join(f"worktree /{path}\0HEAD {SHA}\0detached\0\0" for path in paths)
    assert [w.path for w in parse_worktree_list(text)] == [f"/{path}" for path in paths]
