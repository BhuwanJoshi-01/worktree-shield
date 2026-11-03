"""Worktree Shield: audit parallel Git worktrees for shared resources."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("worktree-shield")
except PackageNotFoundError:  # imported from a source tree that was never installed
    __version__ = "0+unknown"
