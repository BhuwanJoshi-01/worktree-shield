"""The repository policy file, .worktree-shield.toml (WTS-002)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.fakes import read_fixture
from worktree_shield.models import Policy, PolicyLevel

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-002")


def _parse(text: str, source: str = ".worktree-shield.toml") -> Policy:
    from worktree_shield.config import parse_policy

    return parse_policy(text, source)


def test_no_settings_means_the_defaults() -> None:
    assert _parse("schema_version = 1\n") == Policy(source=".worktree-shield.toml")


def test_every_key() -> None:
    policy = _parse(read_fixture("policy", "complete.toml"), "repo/.worktree-shield.toml")
    assert policy == Policy(
        include_runtime=False,
        include_env_files=True,
        max_file_bytes=65536,
        shared_host_ports=PolicyLevel.WARN,
        shared_database=PolicyLevel.DENY,
        shared_compose_projects=PolicyLevel.DENY,
        fixed_container_names=PolicyLevel.ALLOW,
        shared_absolute_paths=PolicyLevel.DENY,
        allow_ports=(5432, 6379),
        allow_paths=("/tmp/shared-download-cache",),  # noqa: S108
        source="repo/.worktree-shield.toml",
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "schema_version"),
        ("schema_version = 2\n", "schema_version 2 is not supported"),
        (
            "schema_version = 1\n[scan]\ninclude_runtime = 'yes'\n",
            "scan.include_runtime must be true or false",
        ),
        (
            "schema_version = 1\n[policy]\nshared_database = 'maybe'\n",
            "policy.shared_database must be one of allow, warn, deny",
        ),
        ("schema_version = 1\n[allow]\nports = [70000]\n", "allow.ports must be port numbers"),
        ("schema_version = 1\n[allow]\nports = 5432\n", "allow.ports must be port numbers"),
        (
            "schema_version = 1\n[allow]\npaths = ['relative/dir']\n",
            "allow.paths must be absolute paths",
        ),
        ("schema_version = 1\n[scan]\nmax_file_bytes = 0\n", "scan.max_file_bytes"),
        ("schema_version = 1\n[scan]\nmax_file_bytes = true\n", "scan.max_file_bytes"),
        ("schema_version = 1\n[sacn]\n", "unknown section [sacn]"),
        (
            "schema_version = 1\n[policy]\nshared_ports = 'deny'\n",
            "unknown key policy.shared_ports",
        ),
        ("schema_version = 1\nextra = 1\n", "unknown key extra"),
        ("schema_version = 1\n[scan\n", "not valid TOML"),
    ],
)
def test_malformed_policies_are_rejected_with_a_clear_message(text: str, message: str) -> None:
    from worktree_shield.config import PolicyError

    with pytest.raises(PolicyError, match=re.escape(message)):
        _parse(text)


def test_load_reads_the_file_of_a_worktree(tmp_path: Path) -> None:
    from worktree_shield.config import POLICY_FILE, load_policy

    (tmp_path / POLICY_FILE).write_text("schema_version = 1\n[policy]\nshared_database = 'deny'\n")
    policy = load_policy(tmp_path)
    assert policy.shared_database is PolicyLevel.DENY
    assert policy.source == str(tmp_path / POLICY_FILE)


def test_no_file_means_the_defaults(tmp_path: Path) -> None:
    from worktree_shield.config import load_policy

    assert load_policy(tmp_path) == Policy()


def test_a_policy_file_linking_outside_the_worktree_is_refused(tmp_path: Path) -> None:
    from worktree_shield.config import POLICY_FILE, PolicyError, load_policy

    outside = tmp_path / "outside.toml"
    outside.write_text("schema_version = 1\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    try:
        (worktree / POLICY_FILE).symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are not available")
    with pytest.raises(PolicyError, match="outside the worktree"):
        load_policy(worktree)


def test_an_oversized_policy_file_is_refused(tmp_path: Path) -> None:
    from worktree_shield.config import POLICY_FILE, PolicyError, load_policy

    (tmp_path / POLICY_FILE).write_text("schema_version = 1\n" + "# padding\n" * 10_000)
    with pytest.raises(PolicyError, match="larger than"):
        load_policy(tmp_path)


def test_flags_override_the_file() -> None:
    from worktree_shield.config import apply_overrides

    policy = _parse("schema_version = 1\n[scan]\ninclude_runtime = true\n")
    overridden = apply_overrides(policy, include_runtime=False, include_env_files=True)
    assert (overridden.include_runtime, overridden.include_env_files) == (False, True)
    assert apply_overrides(policy) == policy
