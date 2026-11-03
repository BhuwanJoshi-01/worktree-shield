"""All static collectors over one worktree: configuration files, read as data."""

from __future__ import annotations

from worktree_shield.collectors.base import Collected, Scope
from worktree_shield.collectors.envfiles import collect_env_files
from worktree_shield.collectors.layout import config_directories
from worktree_shield.collectors.node import collect_package_json
from worktree_shield.collectors.python import collect_pyproject
from worktree_shield.collectors.vite import collect_vite_config
from worktree_shield.models import Policy


def collect_worktree(scope: Scope, policy: Policy, out: Collected) -> None:
    """Every claim in the configuration of one worktree, directory by directory."""
    for directory in config_directories(scope, out):
        collect_env_files(scope, directory, policy, out)
        collect_package_json(scope, directory, out)
        collect_vite_config(scope, directory, out)
        collect_pyproject(scope, directory, out)
