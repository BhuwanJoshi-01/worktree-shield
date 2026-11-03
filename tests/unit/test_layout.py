"""Which directories of a worktree are searched for configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath

import pytest

from worktree_shield.collectors import layout
from worktree_shield.collectors.base import Collected, Scope
from worktree_shield.collectors.layout import config_directories
from worktree_shield.collectors.static import collect_worktree
from worktree_shield.models import Policy


def _touch(root: Path, *paths: str) -> None:
    for path in paths:
        file = root.joinpath(*path.split("/"))
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("{}\n" if file.name == "package.json" else "PORT=1\n")


def _dirs(root: Path) -> tuple[list[str], Collected]:
    out = Collected()
    found = config_directories(Scope(root, str(root), 1000), out)
    return [d.as_posix() for d in found], out


def test_root_first_then_breadth_first(tmp_path: Path) -> None:
    _touch(tmp_path, "package.json", "services/api/.env.example", "apps/web/package.json")
    assert _dirs(tmp_path)[0] == [".", "apps/web", "services/api"]


def test_dependencies_build_output_fixtures_and_hidden_directories_are_skipped(
    tmp_path: Path,
) -> None:
    _touch(
        tmp_path,
        "node_modules/vite/package.json",
        "dist/package.json",
        "tests/fixtures/app/package.json",
        "examples/demo/package.json",
        ".cache/package.json",
        "tests/package.json",
    )
    assert _dirs(tmp_path)[0] == ["tests"]


def test_the_walk_stops_three_levels_down(tmp_path: Path) -> None:
    _touch(tmp_path, "a/b/c/package.json", "a/b/c/d/package.json")
    assert _dirs(tmp_path)[0] == ["a/b/c"]


def test_other_worktrees_and_submodules_are_not_entered(tmp_path: Path) -> None:
    _touch(tmp_path, "package.json", "worktrees/feature/package.json", "libs/sub/package.json")
    (tmp_path / "worktrees" / "feature" / ".git").write_text(
        "gitdir: /repo/.git/worktrees/feature\n"
    )
    (tmp_path / "libs" / "sub" / ".git").mkdir()
    assert _dirs(tmp_path)[0] == ["."]


def test_links_to_directories_are_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _touch(outside, "package.json")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    try:
        (worktree / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not available")
    assert _dirs(worktree)[0] == []


@pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "geteuid", lambda: 0)() == 0,
    reason="needs POSIX permissions and a non-root user",
)
def test_a_directory_that_cannot_be_listed_is_reported(tmp_path: Path) -> None:
    _touch(tmp_path, "locked/package.json")
    (tmp_path / "locked").chmod(0)
    try:
        found, out = _dirs(tmp_path)
    finally:
        (tmp_path / "locked").chmod(0o755)
    assert found == []
    (skipped,) = out.skipped
    assert (skipped.source.path, skipped.reason) == (
        "locked",
        "could not be listed (Permission denied)",
    )


def test_a_huge_tree_is_cut_off_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(layout, "MAX_DIRECTORIES", 3)
    _touch(tmp_path, "a/package.json", "b/package.json", "c/package.json", "d/package.json")
    found, out = _dirs(tmp_path)
    assert found == ["a", "b"]
    assert out.skipped[0].reason.startswith("was not searched: the walk stopped after 3")


def test_a_worktree_with_several_apps(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("DATABASE_URL=postgres://localhost/app_dev\n")
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "vite.config.ts").write_text(
        "export default { server: { port: 5173 } }\n"
    )
    (tmp_path / "apps" / "web" / "package.json").write_text(
        '{"scripts": {"e2e": "vite --port 4000"}}'
    )
    (tmp_path / "services" / "api").mkdir(parents=True)
    (tmp_path / "services" / "api" / "pyproject.toml").write_text(
        '[tool.poe.tasks]\nserve = "uvicorn api:app --port 8000"\n'
    )
    out = Collected()
    collect_worktree(Scope(tmp_path, "/repos/app", 262_144), Policy(), out)
    assert [(c.key, c.source.path) for c in out.claims] == [
        ("db://postgres/localhost:5432/app_dev", ".env.example"),
        ("tcp://*:4000", "apps/web/package.json"),
        ("tcp://*:5173", "apps/web/vite.config.ts"),
        ("tcp://*:8000", "services/api/pyproject.toml"),
    ]


def test_relative_directory_names_are_posix(tmp_path: Path) -> None:
    _touch(tmp_path, "apps/web/package.json")
    out = Collected()
    assert config_directories(Scope(tmp_path, "wt", 100), out) == [PurePosixPath("apps/web")]


def test_an_entry_that_vanishes_while_listed_is_not_entered() -> None:
    class Vanished:
        name = "apps"
        path = "/nonexistent/apps"

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            raise FileNotFoundError(2, "No such file or directory")

    assert layout._worth_entering(Vanished()) is False  # type: ignore[arg-type]
