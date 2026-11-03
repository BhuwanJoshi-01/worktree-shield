"""Build a repository whose three worktrees collide, to try worktree-shield on.

    python examples/conflicting-worktrees/build.py DIR           # the collisions
    python examples/conflicting-worktrees/build.py DIR --fixed   # the same, fixed

DIR must not exist yet. It gets a repository ``app`` and two more worktrees,
``app-login`` and ``app-billing``, which all start a dev server on 5173, use the
database app_dev and run the Compose project ``app``:

    worktree-shield scan --repo DIR/app --strict --scope static   # exits 1

With --fixed, each branch commits its own port, database name and project name, and
the same scan exits 0. Nothing outside DIR is touched; the script needs only git.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

COMPOSE = """\
name: app
services:
  db:
    image: postgres:17
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata: {}
"""
FIXED_COMPOSE = COMPOSE.replace("name: app\n", "")  # the directory name tells them apart


def git(cwd: Path, *args: str) -> None:
    env = {
        "GIT_AUTHOR_NAME": "worktree-shield example",
        "GIT_AUTHOR_EMAIL": "example@example.invalid",
        "GIT_COMMITTER_NAME": "worktree-shield example",
        "GIT_COMMITTER_EMAIL": "example@example.invalid",
        **os.environ,
    }
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True)  # noqa: S603, S607


def env_example(port: int, database: str) -> str:
    return f"PORT={port}\nDATABASE_URL=postgres://app:change-me@localhost:5432/{database}\n"


def build(root: Path, *, fixed: bool) -> Path:
    main = root / "app"
    main.mkdir(parents=True)
    git(main, "init", "-q", "-b", "main")
    (main / ".env.example").write_text(env_example(5173, "app_dev"), encoding="utf-8")
    (main / "compose.yaml").write_text(FIXED_COMPOSE if fixed else COMPOSE, encoding="utf-8")
    (main / "README.md").write_text("A sample app with three worktrees.\n", encoding="utf-8")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "Start the app")
    for offset, name in enumerate(("login", "billing"), start=1):
        worktree = root / f"app-{name}"
        git(main, "worktree", "add", "-q", "-b", name, str(worktree))
        if fixed:
            text = env_example(5173 + offset, f"app_dev_{name}")
            (worktree / ".env.example").write_text(text, encoding="utf-8")
            git(worktree, "commit", "-q", "-am", f"Give {name} its own port and database")
    return main


def main(argv: list[str]) -> int:
    arguments = [a for a in argv if a != "--fixed"]
    if len(arguments) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(arguments[0])
    if root.exists():
        print(f"{root} exists; choose a new directory", file=sys.stderr)
        return 2
    main_worktree = build(root, fixed="--fixed" in argv)
    print(f"Built {main_worktree} and its worktrees app-login and app-billing.")
    print(f"Try: worktree-shield scan --repo {main_worktree}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
