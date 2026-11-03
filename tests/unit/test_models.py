import dataclasses
import re

import pytest

from worktree_shield.models import (
    SCHEMA_VERSION,
    Certainty,
    Confidence,
    Evidence,
    FailureKind,
    Finding,
    ProbeFailure,
    Severity,
    Snapshot,
    SourceRef,
    Status,
    utc_timestamp,
)


def test_status_values_are_the_documented_json_strings() -> None:
    assert [s.value for s in Status] == [
        "pass",
        "warn",
        "fail",
        "unknown",
        "not_applicable",
        "not_tested",
    ]


def test_certainty_runs_from_confirmed_to_unknown() -> None:
    assert [c.value for c in Certainty] == ["confirmed", "probable", "possible", "unknown"]


def test_enums_compare_equal_to_their_json_strings() -> None:
    assert Status.UNKNOWN == "unknown"
    assert Severity.HIGH == "high"
    assert Confidence.MEDIUM == "medium"
    assert Certainty.PROBABLE == "probable"


def _finding(**overrides: object) -> Finding:
    values: dict[str, object] = {
        "id": "WTS-PORT-001",
        "status": Status.WARN,
        "severity": Severity.MEDIUM,
        "confidence": Confidence.HIGH,
        "summary": "Two worktrees declare listen port 5173.",
        "reason": "Both .env.example files set PORT=5173.",
    }
    values.update(overrides)
    return Finding(**values)  # type: ignore[arg-type]


def test_finding_defaults_to_no_resource_and_no_evidence() -> None:
    finding = _finding()
    assert finding.resource_key is None
    assert finding.certainty is None
    assert finding.worktrees == ()
    assert finding.sources == ()
    assert finding.evidence == ()


def test_finding_carries_the_resource_and_where_it_was_claimed() -> None:
    finding = _finding(
        resource_key="tcp://*:5173",
        certainty=Certainty.PROBABLE,
        worktrees=("main", "feature-login"),
        sources=(
            SourceRef("main", ".env.example", 4),
            SourceRef("feature-login", ".env.example", 4),
        ),
    )
    assert finding.sources[1] == SourceRef("feature-login", ".env.example", 4)


@pytest.mark.parametrize(
    "bad_id", ["WTS-PORT-1", "wts-port-001", "SSD-PORT-001", "WTS-PORT-0011", ""]
)
def test_finding_rejects_malformed_ids(bad_id: str) -> None:
    with pytest.raises(ValueError, match="does not match"):
        _finding(id=bad_id)


def test_finding_rejects_malformed_causes_and_empty_summaries() -> None:
    with pytest.raises(ValueError, match="caused_by"):
        _finding(caused_by="GIT-001")
    with pytest.raises(ValueError, match="empty summary"):
        _finding(summary="  ")


def test_findings_and_evidence_are_immutable() -> None:
    finding = _finding(evidence=(Evidence("git", "worktrees", "3"),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.status = Status.PASS  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.evidence[0].value = "1"  # type: ignore[misc]


def test_failure_kinds_are_the_documented_json_strings() -> None:
    assert [k.value for k in FailureKind] == [
        "not_found",
        "permission_denied",
        "timeout",
        "nonzero_exit",
        "malformed_output",
        "os_error",
        "probe_error",
    ]


def test_probe_failure_keeps_probe_kind_and_detail() -> None:
    failure = ProbeFailure("git", FailureKind.TIMEOUT, "no answer within 10 s")
    assert (failure.probe, failure.kind, failure.detail) == (
        "git",
        FailureKind.TIMEOUT,
        "no answer within 10 s",
    )


def test_snapshot_carries_schema_and_tool_version() -> None:
    snapshot = Snapshot(tool_version="0.1.0", created_at="2026-11-03T10:00:00Z")
    assert snapshot.schema_version == SCHEMA_VERSION == 1
    assert snapshot.findings == ()
    assert snapshot.probe_failures == ()


def test_utc_timestamp_is_iso_8601_utc() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", utc_timestamp())
