"""Listening processes tied to worktrees by their working directory (WTS-007)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from worktree_shield.models import Observation, ResourceKind


@dataclass
class FakeTable:
    """Sockets and processes as a test describes them; nothing is read from the system."""

    sockets: list[tuple[str, str, int, int | None]]
    processes: dict[int, tuple[str, str | None] | str] = field(default_factory=dict)
    limitation: str | None = None

    def listening_sockets(self) -> tuple[list[Any], str | None]:
        from worktree_shield.collectors.runtime import Socket

        return [Socket(*s) for s in self.sockets], self.limitation

    def process(self, pid: int) -> tuple[str, str | None]:
        from worktree_shield.collectors.runtime import ProcessDeniedError, ProcessGoneError

        found = self.processes[pid]
        if found == "gone":
            raise ProcessGoneError
        if found == "denied":
            raise ProcessDeniedError
        assert isinstance(found, tuple)
        return found


def _observe(table: FakeTable, worktrees: list[str]) -> Any:
    from worktree_shield.collectors.runtime import observe_runtime

    return observe_runtime(table, worktrees)


@pytest.fixture
def trees(tmp_path: Path) -> list[str]:
    main = tmp_path / "app"
    (main / "worktrees" / "feature" / "src").mkdir(parents=True)
    (tmp_path / "app-login").mkdir()
    return [str(main), str(main / "worktrees" / "feature"), str(tmp_path / "app-login")]


def test_a_listener_is_tied_to_the_worktree_it_runs_in(trees: list[str]) -> None:
    table = FakeTable(
        [("tcp", "127.0.0.1", 5173, 10), ("tcp", "::", 8000, 11)],
        {10: ("node", trees[2]), 11: ("python3", str(Path(trees[1], "src")))},
    )
    claims, unattributed, limitations = _observe(table, trees)
    assert [(c.key, c.worktree, c.observation, c.source.path) for c in claims] == [
        ("tcp://127.0.0.1:5173", trees[2], Observation.RUNTIME, "pid 10"),
        ("tcp://[::]:8000", trees[1], Observation.RUNTIME, "pid 11"),  # the nested worktree
    ]
    assert claims[0].kind is ResourceKind.LISTEN_PORT
    assert claims[0].detail == "node (pid 10) is listening; it runs in this worktree"
    assert (unattributed, limitations) == ([], [])


def test_processes_that_cannot_be_tied_are_kept_with_the_reason(trees: list[str]) -> None:
    table = FakeTable(
        [
            ("tcp", "0.0.0.0", 5432, None),
            ("tcp", "127.0.0.1", 3000, 20),
            ("tcp", "127.0.0.1", 3001, 21),
            ("udp", "0.0.0.0", 5353, 22),
            ("tcp", "127.0.0.1", 9000, 23),
        ],
        {20: "gone", 21: "denied", 22: ("avahi", None), 23: ("code", "/somewhere/else")},
        limitation="the sockets of other users' processes are listed without their owner",
    )
    claims, unattributed, limitations = _observe(table, trees)
    assert claims == []
    assert [(u.port, u.pid, u.process, u.note) for u in unattributed] == [
        (5432, None, None, "owned by a process of another user"),
        (3000, 20, None, "the process ended while it was looked at"),
        (3001, 21, None, "the process cannot be inspected without more privileges"),
        (5353, 22, "avahi", "its working directory cannot be read"),
        (9000, 23, "code", "it runs outside every worktree"),
    ]
    assert limitations == ["the sockets of other users' processes are listed without their owner"]


def test_a_directory_with_a_shared_prefix_is_not_inside(trees: list[str], tmp_path: Path) -> None:
    sibling = tmp_path / "app-login-old"
    sibling.mkdir()
    table = FakeTable([("tcp", "127.0.0.1", 1, 1)], {1: ("node", str(sibling))})
    claims, unattributed, _ = _observe(table, trees)
    assert claims == []
    assert unattributed[0].note == "it runs outside every worktree"


def test_a_link_to_a_worktree_counts_as_the_worktree(trees: list[str], tmp_path: Path) -> None:
    link = tmp_path / "current"
    try:
        link.symlink_to(trees[2], target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not available")
    table = FakeTable([("tcp", "127.0.0.1", 1, 1)], {1: ("node", trees[2])})
    claims, _, _ = _observe(table, [str(link)])
    assert [c.worktree for c in claims] == [str(link)]


def test_each_process_is_looked_up_once(trees: list[str]) -> None:
    calls: list[int] = []

    class Counting(FakeTable):
        def process(self, pid: int) -> tuple[str, str | None]:
            calls.append(pid)
            return super().process(pid)

    table = Counting([("tcp", "127.0.0.1", 1, 7), ("tcp", "::1", 1, 7)], {7: ("node", trees[0])})
    claims, _, _ = _observe(table, trees)
    assert len(claims) == 2
    assert calls == [7]
