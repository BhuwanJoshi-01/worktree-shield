"""Real Git repositories with several worktrees, built in temporary directories.

The helper runs git with the user's global and system configuration switched off, so
tests behave the same on every machine; the code under test runs git normally.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - test helper, fixed git commands
        ["git", *args],  # noqa: S607
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


def make_repo(root: Path, name: str = "app") -> Path:
    """A repository with one commit; returns the main worktree."""
    main = root / name
    main.mkdir(parents=True)
    git(main, "init", "-q", "-b", "main")
    (main / "README.md").write_text("app\n", encoding="utf-8")
    git(main, "add", "README.md")
    git(main, "commit", "-q", "-m", "init")
    return main


def add_worktree(main: Path, path: Path, branch: str | None = None) -> Path:
    if branch is None:
        git(main, "worktree", "add", "-q", "--detach", str(path))
    else:
        git(main, "worktree", "add", "-q", "-b", branch, str(path))
    return path


def tree_digest(directory: Path) -> str:
    """Names, sizes, modification times and contents of every file under ``directory``.

    Equal before and after a scan means the scan wrote nothing there, not even a lock
    file or a refreshed index timestamp.
    """
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            stat = path.stat()
            digest.update(str(path.relative_to(directory)).encode())
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def same_path(a: str | Path | None, b: str | Path) -> bool:
    """Git prints forward slashes on Windows; compare the paths, not the strings."""
    if a is None:
        return False
    return os.path.normcase(Path(a).resolve()) == os.path.normcase(Path(b).resolve())
