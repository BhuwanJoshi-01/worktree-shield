"""Reading configuration from a worktree without leaving it."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from worktree_shield.files import RefusedError, read_inside, read_text_inside


def _link(link: Path, target: str | Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are not available")


def test_a_missing_file_is_none(tmp_path: Path) -> None:
    assert read_inside(tmp_path, "package.json", 100) is None


def test_a_file_in_a_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / ".env.example").write_bytes(b"PORT=5173\n")
    assert read_inside(tmp_path, Path("apps", "web", ".env.example"), 100) == b"PORT=5173\n"


def test_a_file_of_exactly_the_cap_is_read(tmp_path: Path) -> None:
    (tmp_path / "f").write_bytes(b"x" * 100)
    assert read_inside(tmp_path, "f", 100) == b"x" * 100


def test_a_file_over_the_cap_is_refused_not_cut(tmp_path: Path) -> None:
    (tmp_path / "f").write_bytes(b"x" * 101)
    with pytest.raises(RefusedError, match="is larger than 100 bytes"):
        read_inside(tmp_path, "f", 100)


def test_a_link_within_the_worktree_is_followed(tmp_path: Path) -> None:
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "base.env").write_bytes(b"PORT=1\n")
    _link(tmp_path / ".env.example", Path("shared", "base.env"))
    assert read_inside(tmp_path, ".env.example", 100) == b"PORT=1\n"


def test_a_link_out_of_the_worktree_is_refused(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (tmp_path / "secret.env").write_bytes(b"DB_PASSWORD=x\n")
    _link(worktree / ".env.example", tmp_path / "secret.env")
    with pytest.raises(RefusedError, match="outside the worktree"):
        read_inside(worktree, ".env.example", 100)


def test_a_directory_link_out_of_the_worktree_is_refused(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "package.json").write_bytes(b"{}")
    worktree.mkdir()
    _link(worktree / "apps", tmp_path / "elsewhere")
    with pytest.raises(RefusedError, match="outside the worktree"):
        read_inside(worktree, Path("apps", "package.json"), 100)


def test_dot_dot_does_not_leave_the_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (tmp_path / "outside.toml").write_bytes(b"x")
    with pytest.raises(RefusedError, match="outside the worktree"):
        read_inside(worktree, Path("..", "outside.toml"), 100)


def test_a_dangling_link(tmp_path: Path) -> None:
    _link(tmp_path / "compose.yaml", "missing.yaml")
    with pytest.raises(RefusedError, match="does not exist"):
        read_inside(tmp_path, "compose.yaml", 100)


def test_a_directory(tmp_path: Path) -> None:
    (tmp_path / "package.json").mkdir()
    with pytest.raises(RefusedError, match="not a regular file"):
        read_inside(tmp_path, "package.json", 100)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
def test_a_named_pipe_never_blocks(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / ".env")
    with pytest.raises(RefusedError, match="not a regular file"):
        read_inside(tmp_path, ".env", 100)


@pytest.mark.skipif(
    sys.platform == "win32" or getattr(os, "geteuid", lambda: 0)() == 0,
    reason="needs POSIX permissions and a non-root user",
)
def test_an_unreadable_file(tmp_path: Path) -> None:
    secret = tmp_path / ".env"
    secret.write_bytes(b"PORT=1\n")
    secret.chmod(0)
    try:
        with pytest.raises(RefusedError, match=r"could not be read \(Permission denied\)"):
            read_inside(tmp_path, ".env", 100)
    finally:
        secret.chmod(0o600)


def test_text_drops_a_byte_order_mark(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_bytes(b"\xef\xbb\xbfPORT=1\n")
    assert read_text_inside(tmp_path, ".env.example", 100) == "PORT=1\n"


def test_text_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_bytes(b"NAME=caf\xe9\n")
    with pytest.raises(RefusedError, match="not UTF-8"):
        read_text_inside(tmp_path, ".env.example", 100)


def test_text_of_a_missing_file_is_none(tmp_path: Path) -> None:
    assert read_text_inside(tmp_path, ".env.example", 100) is None


def test_a_file_swapped_for_a_pipe_after_the_check_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stat

    from worktree_shield import files

    (tmp_path / ".env").write_bytes(b"PORT=1\n")
    pipe = os.stat_result((stat.S_IFIFO | 0o600, 0, 0, 1, 0, 0, 0, 0, 0, 0))
    monkeypatch.setattr(files.os, "fstat", lambda fd: pipe)
    with pytest.raises(RefusedError, match="not a regular file"):
        read_inside(tmp_path, ".env", 100)


def test_a_read_error_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from worktree_shield import files

    (tmp_path / ".env").write_bytes(b"PORT=1\n")

    def broken(fd: int, size: int) -> bytes:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(files.os, "read", broken)
    with pytest.raises(RefusedError, match=r"could not be read \(Input/output error\)"):
        read_inside(tmp_path, ".env", 100)
