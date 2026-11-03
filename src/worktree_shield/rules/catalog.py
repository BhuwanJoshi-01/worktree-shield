"""The built-in rules, in the order reports list them."""

from __future__ import annotations

from worktree_shield.rules import context, runtime, shared
from worktree_shield.rules.engine import Rule

_ORDER = (
    "WTS-PORT-001",
    "WTS-PORT-002",
    "WTS-DB-001",
    "WTS-DB-002",
    "WTS-DOCKER-001",
    "WTS-DOCKER-002",
    "WTS-DOCKER-003",
    "WTS-PATH-001",
    "WTS-ENV-001",
    "WTS-CONFIG-001",
    "WTS-GIT-002",
    "WTS-RUNTIME-001",
    "WTS-POLICY-001",
)


def builtin_rules() -> tuple[Rule, ...]:
    """Every rule, ordered by resource: ports, databases, Docker, paths, then context."""
    rules = {rule.id: rule for rule in (*shared.RULES, *runtime.RULES, *context.RULES)}
    return tuple(rules[rule_id] for rule_id in _ORDER)
