"""What every collector shares: where it reads from and where its results go."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

from worktree_shield.files import RefusedError, read_text_inside
from worktree_shield.models import ResourceClaim, SkippedFile, SourceRef, UnreadableValue


@dataclass
class Collected:
    """The results of the collectors of one scan, in the order they were found."""

    claims: list[ResourceClaim] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)
    unreadable: list[UnreadableValue] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Scope:
    """One worktree: ``root`` is read from, ``worktree`` is how reports name it (the
    path Git lists). Files are named by their POSIX path relative to the root."""

    root: Path
    worktree: str
    max_bytes: int

    def source(self, relative: PurePosixPath, line: int | None = None) -> SourceRef:
        return SourceRef(self.worktree, relative.as_posix(), line)

    def read(self, relative: PurePosixPath, out: Collected) -> str | None:
        """The text of a file, ``None`` if it does not exist; a refused file is recorded
        in ``out.skipped`` and also gives ``None``."""
        try:
            return read_text_inside(self.root, Path(*relative.parts), self.max_bytes)
        except RefusedError as error:
            out.skipped.append(SkippedFile(self.source(relative), str(error)))
            return None


def is_absolute_path(value: str) -> bool:
    """An absolute POSIX or Windows path below the root (``/`` and ``C:\\`` are not)."""
    if "://" in value:
        return False
    for flavour in (PurePosixPath, PureWindowsPath):
        path = flavour(value)
        if path.is_absolute():
            return len(path.parts) > 1
    return False


def path_key(value: str) -> str:
    """``path:///srv/cache`` for an absolute path, trailing separators removed."""
    return "path://" + value.rstrip("/\\")


def tcp_key(host: str | None, port: int, default: str = "*") -> str:
    """``tcp://127.0.0.1:5173``; ``default`` stands for a host the config leaves open."""
    server = host or default
    return f"tcp://[{server}]:{port}" if ":" in server else f"tcp://{server}:{port}"
