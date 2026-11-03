"""JavaScript and TypeScript source with comments and literals blanked out.

Nothing is evaluated. :func:`blank_code` returns the source with the *contents* of
comments, strings, template literals and regular expressions replaced by spaces (quotes
and newlines kept, so positions and line numbers do not move). Patterns matched against
the result only see code: ``"server: { port: 9999 }"`` inside a string or a commented-out
block no longer looks like a setting. Literal values are then read from the original
text at the same position.

It is a lexer, not a parser: a ``/`` counts as the start of a regular expression when
the previous code character cannot end an operand, which is right for configuration
files but not for every program.
"""

from __future__ import annotations

_OPERAND_END = frozenset(")]}")  # after these (and names, numbers, literals) "/" divides


def blank_code(source: str) -> str:
    """``source`` with comment and literal contents replaced by spaces."""
    out = list(source)
    _code(source, 0, out, nested=False)
    return "".join(out)


def _blank(out: list[str], start: int, end: int) -> None:
    for index in range(start, min(end, len(out))):
        if out[index] != "\n":
            out[index] = " "


def _code(source: str, index: int, out: list[str], *, nested: bool) -> int:
    """Scan code from ``index``; inside a template ``${…}`` stop after its ``}``."""
    length = len(source)
    depth = 0
    previous = ""  # the last code character, to tell a regex from a division
    while index < length:
        char = source[index]
        pair = source[index : index + 2]
        if pair == "//":
            end = source.find("\n", index)
            end = length if end < 0 else end
            _blank(out, index, end)
            index = end
        elif pair == "/*":
            end = source.find("*/", index + 2)
            end = length if end < 0 else end + 2
            _blank(out, index, end)
            index = end
        elif char in "'\"":
            closing, end = _string_end(source, index, char)
            _blank(out, index + 1, closing)
            index, previous = end, "a"
        elif char == "`":
            index, previous = _template(source, index, out), "a"
        elif char == "/" and not _ends_operand(previous):
            regex = _regex_end(source, index)
            if regex is None:  # not a regex after all: a lone slash
                index, previous = index + 1, char
                continue
            _blank(out, index + 1, regex[0])
            index, previous = regex[1], "a"
        else:
            if nested and char == "{":
                depth += 1
            elif nested and char == "}":
                if depth == 0:
                    return index + 1
                depth -= 1
            if not char.isspace():
                previous = char
            index += 1
    return index


def _ends_operand(previous: str) -> bool:
    """Whether a ``/`` after this character divides rather than starts a regex."""
    return previous.isalnum() or previous in "_$" or previous in _OPERAND_END


def _string_end(source: str, start: int, quote: str) -> tuple[int, int]:
    """Where the contents end and where code resumes: after the closing quote, or at the
    end of the line when the string is never closed."""
    index = start + 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index, index + 1
        if char == "\n":
            return index, index
        index += 1
    return len(source), len(source)


def _template(source: str, start: int, out: list[str]) -> int:
    """Blank a template literal's text, scan its ``${…}`` parts as code."""
    index = start + 1
    text_from = index
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
        elif char == "`":
            _blank(out, text_from, index)
            return index + 1
        elif source.startswith("${", index):
            _blank(out, text_from, index)
            index = _code(source, index + 2, out, nested=True)
            text_from = index
        else:
            index += 1
    _blank(out, text_from, len(source))
    return len(source)


def _regex_end(source: str, start: int) -> tuple[int, int] | None:
    """The closing ``/`` of a regex literal and the index after its flags, or ``None``
    when the line ends first."""
    index = start + 1
    in_class = False
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n":
            return None
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            end = index + 1
            while end < len(source) and source[end].isalpha():
                end += 1
            return index, end
        index += 1
    return None
