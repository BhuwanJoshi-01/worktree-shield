"""docs/rules.md documents every rule in the catalog, under its title."""

from __future__ import annotations

import re
from pathlib import Path

from worktree_shield.rules.catalog import builtin_rules

RULES_DOC = Path(__file__).parents[2] / "docs" / "rules.md"


def test_every_rule_is_documented_with_its_title() -> None:
    headings = dict(
        re.findall(r"^## (WTS-[A-Z]+-\d{3}): (.+)$", RULES_DOC.read_text(encoding="utf-8"), re.M)
    )
    assert headings == {rule.id: rule.title for rule in builtin_rules()}
