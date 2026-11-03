"""Parse ``git worktree list --porcelain -z``.

With ``-z`` every attribute ends with NUL and every record with one more NUL, so paths
with spaces, newlines or any other byte except NUL come through intact. This is the
format Git documents as stable for scripts; the human-readable list is never parsed.
"""

from __future__ import annotations

from worktree_shield.models import Worktree


class PorcelainError(ValueError):
    """The output is not a worktree list."""


def parse_worktree_list(text: str) -> tuple[Worktree, ...]:
    """The worktrees in Git's order: the main worktree first, then the linked ones.

    Unknown attributes are skipped, so a newer Git that adds one does not break the
    scan. A record without a ``worktree`` line is an error.
    """
    worktrees: list[Worktree] = []
    for record in text.split("\0\0"):
        attributes = [item for item in record.split("\0") if item]
        if not attributes:
            continue
        name, _, path = attributes[0].partition(" ")
        if name != "worktree" or not path:
            raise PorcelainError(f"a record starts with {name!r}, not 'worktree <path>'")
        head = branch = locked = prunable = None
        bare = detached = False
        for attribute in attributes[1:]:
            key, space, value = attribute.partition(" ")
            if key == "HEAD":
                head = value or None
            elif key == "branch":
                branch = value or None
            elif key == "bare":
                bare = True
            elif key == "detached":
                detached = True
            elif key == "locked":
                locked = value if space else ""
            elif key == "prunable":
                prunable = value if space else ""
        worktrees.append(Worktree(path, head, branch, bare, detached, locked, prunable))
    return tuple(worktrees)
