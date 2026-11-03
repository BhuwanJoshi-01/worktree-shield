"""Reading a configuration file of a worktree, and nothing outside it.

Every file worktree-shield reads from a repository goes through :func:`read_inside`:
links may point elsewhere in the worktree but not out of it, only regular files are
opened (a named pipe would block, a device could be endless), and a file larger than
the cap is refused rather than read in part, since half a file can mean something else.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
_FLAGS |= getattr(os, "O_BINARY", 0)


class RefusedError(Exception):
    """The file exists but was not read; ``str()`` completes "<path> …" for a report."""


def read_inside(root: Path, relative: str | Path, max_bytes: int) -> bytes | None:
    """The bytes of ``root / relative``, or ``None`` when there is no such file.

    Raises :class:`RefusedError` when the file must not be read: a link out of ``root``,
    not a regular file, larger than ``max_bytes`` or unreadable.
    """
    path = root / relative
    if not os.path.lexists(path):
        return None
    try:
        target = path.resolve(strict=True)
        if not target.is_relative_to(root.resolve(strict=True)):
            raise RefusedError("is a link to a file outside the worktree")
        if not stat.S_ISREG(target.stat().st_mode):  # Windows cannot open() a directory
            raise RefusedError("is not a regular file")
        # Checked again on what was opened: a file swapped for a pipe after the check
        # cannot block (O_NONBLOCK) and is refused by fstat().
        fd = os.open(target, _FLAGS)
    except FileNotFoundError:
        raise RefusedError("could not be read (a link to a file that does not exist)") from None
    except OSError as error:
        raise RefusedError(f"could not be read ({error.strerror or error})") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RefusedError("is not a regular file")
        chunks: list[bytes] = []
        size = 0
        while size <= max_bytes and (chunk := os.read(fd, max_bytes + 1 - size)):
            chunks.append(chunk)
            size += len(chunk)
    except OSError as error:
        raise RefusedError(f"could not be read ({error.strerror or error})") from None
    finally:
        os.close(fd)
    if size > max_bytes:
        raise RefusedError(f"is larger than {max_bytes} bytes")
    return b"".join(chunks)


def read_text_inside(root: Path, relative: str | Path, max_bytes: int) -> str | None:
    """Like :func:`read_inside`, decoded as UTF-8 (a byte order mark is dropped)."""
    raw = read_inside(root, relative, max_bytes)
    if raw is None:
        return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RefusedError("is not UTF-8 text") from None
