"""JSON output: the diagnosed snapshot as plain data, for CI, agents and bug reports.

The format is versioned by ``schema_version`` and described by docs/json-schema-v1.json;
a contract test keeps the two in step. Pass a redacted snapshot.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from worktree_shield.models import Snapshot, Status

WORST_FIRST = (
    Status.FAIL,
    Status.WARN,
    Status.UNKNOWN,
    Status.PASS,
    Status.NOT_TESTED,
    Status.NOT_APPLICABLE,
)


def summary(snapshot: Snapshot) -> dict[str, Any]:
    """What a script looks at first; every value follows from the findings."""
    counts = Counter(finding.status for finding in snapshot.findings)
    worst = next((status.value for status in WORST_FIRST if counts.get(status)), None)
    repository = snapshot.repository
    return {
        "worktrees": len(repository.worktrees) if repository is not None else None,
        "counts": {status.value: counts.get(status, 0) for status in Status},
        "worst": worst,
        "strict_failure": counts.get(Status.FAIL, 0) > 0,
    }


def snapshot_to_dict(snapshot: Snapshot) -> dict[str, Any]:
    """Plain dicts, lists and scalars; enums become their documented string values."""
    plain = _plain(snapshot)
    if not isinstance(plain, dict):  # pragma: no cover - a dataclass becomes a dict
        raise TypeError("snapshot did not serialise to an object")
    plain["summary"] = summary(snapshot)
    return plain


def render_json(snapshot: Snapshot) -> str:
    """Indented JSON with a trailing newline."""
    return json.dumps(snapshot_to_dict(snapshot), indent=2, ensure_ascii=False) + "\n"


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value
