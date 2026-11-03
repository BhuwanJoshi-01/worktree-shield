"""Which directories of a worktree hold configuration worth reading.

Monorepos keep a ``package.json`` or ``.env.example`` per app (``apps/web``,
``services/api``), so the root alone is not enough, but the whole tree is too much:
the walk lists directories only (no file is opened here), goes at most
:data:`MAX_DEPTH` levels down, never follows a link to a directory, and skips
dependencies, build output, test fixtures and examples, which declare ports nobody runs
from this worktree.

A directory with a ``.git`` entry of its own is another worktree or a submodule and is
not entered: worktrees often live inside the main one (``repo/worktrees/feature``), and
their files must not be counted twice, once as the main worktree's.
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path, PurePosixPath

from worktree_shield.collectors.base import Collected, Scope
from worktree_shield.collectors.compose import COMPOSE_FILES, OVERRIDE_FILES
from worktree_shield.collectors.envfiles import LOCAL_FILES, TEMPLATE_FILES
from worktree_shield.collectors.vite import CONFIG_FILES as VITE_FILES
from worktree_shield.models import SkippedFile

MAX_DEPTH = 3
MAX_DIRECTORIES = 2000
CONFIG_NAMES = frozenset(
    (
        *TEMPLATE_FILES,
        *LOCAL_FILES,
        "package.json",
        "pyproject.toml",
        *VITE_FILES,
        *COMPOSE_FILES,
        *OVERRIDE_FILES,
        "Procfile",
        "Procfile.dev",
        ".devcontainer",
        ".devcontainer.json",
    )
)
SKIPPED_DIRECTORIES = frozenset(
    {
        "node_modules",
        "bower_components",
        "vendor",
        "third_party",
        "site-packages",
        "venv",
        "dist",
        "build",
        "out",
        "target",
        "coverage",
        "__pycache__",
        "fixtures",
        "__fixtures__",
        "testdata",
        "examples",
    }
)


def config_directories(scope: Scope, out: Collected) -> list[PurePosixPath]:
    """Directories (relative to the worktree, root first) that contain at least one
    known configuration file, breadth first. A directory that cannot be listed, or a
    walk that reaches :data:`MAX_DIRECTORIES`, is recorded in ``out.skipped``."""
    found: list[PurePosixPath] = []
    queue: deque[PurePosixPath] = deque([PurePosixPath()])
    listed = 0
    while queue:
        relative = queue.popleft()
        listed += 1
        if listed > MAX_DIRECTORIES:
            reason = f"was not searched: the walk stopped after {MAX_DIRECTORIES} directories"
            out.skipped.append(SkippedFile(scope.source(relative), reason))
            break
        try:
            with os.scandir(scope.root.joinpath(*relative.parts)) as listing:
                entries = sorted(listing, key=lambda entry: entry.name)
        except OSError as error:
            reason = f"could not be listed ({error.strerror or error})"
            out.skipped.append(SkippedFile(scope.source(relative), reason))
            continue
        if any(entry.name in CONFIG_NAMES for entry in entries):
            found.append(relative)
        if len(relative.parts) >= MAX_DEPTH:
            continue
        for entry in entries:
            if _worth_entering(entry):
                queue.append(relative / entry.name)
    return found


def _worth_entering(entry: os.DirEntry[str]) -> bool:
    name = entry.name
    if name.startswith(".") or name in SKIPPED_DIRECTORIES:
        return False
    try:
        if not entry.is_dir(follow_symlinks=False):
            return False
        return not os.path.lexists(Path(entry.path, ".git"))  # another worktree or submodule
    except OSError:
        return False
