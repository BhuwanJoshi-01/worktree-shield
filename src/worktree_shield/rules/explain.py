"""The explanation of each rule, from rules.md shipped with the package.

rules.md is a copy of docs/rules.md (a test keeps them identical), so ``explain``
prints exactly what the documentation says.
"""

from __future__ import annotations

import re
from importlib.resources import files

_HEADING = re.compile(r"^## (WTS-[A-Z]+-\d{3}): .+$", re.M)


def rules_text() -> str:
    return files("worktree_shield.rules").joinpath("rules.md").read_text(encoding="utf-8")


def explanation(rule_id: str) -> str | None:
    """The section of a rule, heading included, or ``None`` for an unknown ID."""
    text = rules_text()
    headings = list(_HEADING.finditer(text))
    for index, heading in enumerate(headings):
        if heading.group(1) == rule_id.upper():
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            return text[heading.start() : end].strip() + "\n"
    return None
