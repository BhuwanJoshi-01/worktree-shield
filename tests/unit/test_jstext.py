"""Blanking comments and literals in JavaScript without evaluating it."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from worktree_shield.parsers.jstext import blank_code


@pytest.mark.parametrize(
    ("source", "blanked"),
    [
        ("a // port: 1\nb", "a           \nb"),
        ("a /* x\ny */ b", "a     \n     b"),
        ("x = 'p: 1'", "x = '    '"),
        ('x = "a\\"b"', 'x = "    "'),
        ("x = `t ${y} t`", "x = `  ${y}  `"),
        ("x = `a ${ {b: '}'} } c`", "x = `  ${ {b: ' '} }  `"),
        ("x = /\\{/g, y", "x = /  /g, y"),
        ("a = b / c / d", "a = b / c / d"),
        ("f(x) / 2", "f(x) / 2"),
        ("x = 'unclosed\ny = 1", "x = '        \ny = 1"),
        ("`never closed", "`            "),
        ("a / b\n/ c", "a / b\n/ c"),
        ("x = / 2\n", "x = / 2\n"),
        ("x = `a\\`b`", "x = `    `"),
        ("r = /[/]\\//", "r = /     /"),
        ("r = /abc", "r = /abc"),
    ],
)
def test_blanking(source: str, blanked: str) -> None:
    assert blank_code(source) == blanked


@given(st.text(max_size=300))
def test_positions_and_lines_never_move(source: str) -> None:
    blanked = blank_code(source)
    assert len(blanked) == len(source)
    assert [i for i, c in enumerate(blanked) if c == "\n"] == [
        i for i, c in enumerate(source) if c == "\n"
    ]
