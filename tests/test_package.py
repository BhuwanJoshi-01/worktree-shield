from importlib.metadata import version

import worktree_shield


def test_version_comes_from_installed_metadata() -> None:
    assert worktree_shield.__version__ == version("worktree-shield")
