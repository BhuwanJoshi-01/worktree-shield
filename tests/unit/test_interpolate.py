"""Compose variable interpolation, resolved from files only (WTS-005)."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.xfail(strict=True, reason="WTS-005")


def _run(text: str, **variables: str) -> Any:
    from worktree_shield.parsers.interpolate import interpolate

    result = interpolate(text, variables)
    return result.value, result.missing, result.assumed_unset


@pytest.mark.parametrize(
    ("text", "variables", "expected"),
    [
        ("8000:80", {}, ("8000:80", (), ())),
        ("${WEB_PORT:-8080}:80", {}, ("8080:80", (), ("WEB_PORT",))),
        ("${WEB_PORT:-8080}:80", {"WEB_PORT": "9000"}, ("9000:80", (), ())),
        ("${WEB_PORT:-8080}", {"WEB_PORT": ""}, ("8080", (), ())),
        ("${WEB_PORT-8080}", {"WEB_PORT": ""}, ("", (), ())),
        ("${WEB_PORT-8080}", {}, ("8080", (), ("WEB_PORT",))),
        ("${WEB_PORT}:80", {}, (None, ("WEB_PORT",), ())),
        ("$WEB_PORT:80", {"WEB_PORT": "1"}, ("1:80", (), ())),
        ("$WEB_PORT:80", {}, (None, ("WEB_PORT",), ())),
        ("$$HOME/x", {}, ("$HOME/x", (), ())),
        ("${A:?A is required}", {}, (None, ("A",), ())),
        ("${A:?A is required}", {"A": "x"}, ("x", (), ())),
        ("${A?A is required}", {"A": ""}, ("", (), ())),
        ("${A:?A is required}", {"A": ""}, (None, ("A",), ())),
        ("${A:+on}", {"A": "1"}, ("on", (), ())),
        ("${A:+on}", {}, ("", (), ("A",))),
        ("${A+on}", {"A": ""}, ("on", (), ())),
        ("${A:-${B:-3000}}", {}, ("3000", (), ("A", "B"))),
        ("${A:-${B}}", {}, (None, ("B",), ("A",))),
        ("${A:-}", {}, ("", (), ("A",))),
        ("cost: 5$", {}, ("cost: 5$", (), ())),
        ("${PROJECT}-db", {"PROJECT": "shop"}, ("shop-db", (), ())),
    ],
)
def test_interpolation(text: str, variables: dict[str, str], expected: Any) -> None:
    assert _run(text, **variables) == expected


@pytest.mark.parametrize("text", ["${A", "${}", "${A B}", "${1A}", "${A:x}"])
def test_invalid_syntax_has_no_value(text: str) -> None:
    value, missing, _ = _run(text)
    assert value is None
    assert missing == ()


@given(
    st.text(max_size=200),
    st.dictionaries(st.from_regex(r"[A-Z_]{1,5}", fullmatch=True), st.text(max_size=5)),
)
def test_any_text_is_handled(text: str, variables: dict[str, str]) -> None:
    from worktree_shield.parsers.interpolate import interpolate

    result = interpolate(text, variables)
    assert result.value is None or isinstance(result.value, str)
