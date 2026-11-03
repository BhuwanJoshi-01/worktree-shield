"""The JSON output is a contract: it must match docs/json-schema-v1.json exactly (WTS-009)."""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.fakes import FakeProcessTable
from tests.gitrepos import add_worktree, git, make_repo
from worktree_shield import models
from worktree_shield.models import Snapshot
from worktree_shield.orchestrator import diagnose, inspect_resources
from worktree_shield.privacy import RedactionContext, redact_snapshot
from worktree_shield.reports.json_report import render_json
from worktree_shield.runner import SubprocessRunner

SCHEMA = json.loads((Path(__file__).parents[2] / "docs" / "json-schema-v1.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def validate(document: Any) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in VALIDATOR.iter_errors(document)
    ]


@pytest.fixture
def scanned(tmp_path: Path) -> Snapshot:
    """A real repository with two worktrees, Compose, a skipped file and a runtime view."""
    main = make_repo(tmp_path, "shop")
    (main / ".env.example").write_text(
        "PORT=5173\nDATABASE_URL=postgres://u:p@localhost:5432/shop_dev\nUPLOAD_DIR=/srv/up\n",
        encoding="utf-8",
    )
    (main / "compose.yaml").write_text(
        "name: shop\nservices:\n  db:\n    container_name: shop-db\n    ports: ['5432:5432']\n",
        encoding="utf-8",
    )
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "config")
    login = add_worktree(main, tmp_path / "shop-login", "login")
    (login / "package.json").write_text("{not json", encoding="utf-8")
    (login / ".env").write_text("PORT=1\n", encoding="utf-8")
    table = FakeProcessTable(
        [("tcp", "127.0.0.1", 9000, 5), ("tcp", "0.0.0.0", 5432, None)],
        {5: ("node", str(login))},
        limitation="the sockets of other users' processes are listed without their owner",
    )
    return diagnose(inspect_resources(SubprocessRunner(), main, table=table))


def test_the_schema_itself_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_a_real_scan_matches_the_schema(scanned: Snapshot) -> None:
    document = json.loads(render_json(scanned))
    assert validate(document) == []
    assert document["summary"]["strict_failure"] is True
    assert document["summary"]["worst"] == "fail"
    assert {f["id"] for f in document["findings"]} >= {"WTS-PORT-001", "WTS-DOCKER-002"}
    assert document["claims"]
    assert document["skipped"]
    assert document["runtime"]["limitations"]


def test_an_empty_snapshot_matches_the_schema() -> None:
    document = json.loads(render_json(Snapshot("0.1.0", "2026-11-04T10:00:00Z")))
    assert validate(document) == []
    assert document["summary"] == {
        "worktrees": None,
        "counts": {status.value: 0 for status in models.Status},
        "worst": None,
        "strict_failure": False,
    }


def test_unknown_fields_and_bad_ids_are_rejected(scanned: Snapshot) -> None:
    document = json.loads(render_json(scanned))
    document["claims"][0]["new_field"] = "x"
    assert validate(document)
    document = json.loads(render_json(scanned))
    document["findings"][0]["id"] = "SSD-PORT-001"
    assert validate(document)


SCHEMA_DEFS = {
    models.Snapshot: SCHEMA,
    models.Repository: SCHEMA["$defs"]["repository"],
    models.Worktree: SCHEMA["$defs"]["worktree"],
    models.Policy: SCHEMA["$defs"]["policy"],
    models.ResourceClaim: SCHEMA["$defs"]["claim"],
    models.SourceRef: SCHEMA["$defs"]["source"],
    models.SkippedFile: SCHEMA["$defs"]["skipped_file"],
    models.UnreadableValue: SCHEMA["$defs"]["unreadable_value"],
    models.RuntimeFacts: SCHEMA["$defs"]["runtime"],
    models.Listener: SCHEMA["$defs"]["listener"],
    models.ProbeFailure: SCHEMA["$defs"]["probe_failure"],
    models.Finding: SCHEMA["$defs"]["finding"],
    models.Evidence: SCHEMA["$defs"]["evidence"],
    models.RedactionCount: SCHEMA["$defs"]["redaction_count"],
}
DERIVED = {models.Snapshot: {"summary"}}


@pytest.mark.parametrize("model", list(SCHEMA_DEFS), ids=lambda m: m.__name__)
def test_every_model_field_is_in_the_schema_and_nothing_else(model: type) -> None:
    fields = {f.name for f in dataclasses.fields(model)} | DERIVED.get(model, set())
    schema = SCHEMA_DEFS[model]
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    ("enum", "name"),
    [
        (models.Status, "status"),
        (models.Severity, "severity"),
        (models.Confidence, "confidence"),
        (models.Certainty, "certainty"),
        (models.FailureKind, "failure_kind"),
        (models.PolicyLevel, "policy_level"),
        (models.ResourceKind, "resource_kind"),
        (models.Observation, "observation"),
    ],
)
def test_enums_match_the_schema(enum: type[Enum], name: str) -> None:
    assert SCHEMA["$defs"][name]["enum"] == [member.value for member in enum]


def test_redacted_output_matches_the_schema_and_hides_the_home(scanned: Snapshot) -> None:
    home = str(Path(scanned.repository.worktrees[0].path).parent) if scanned.repository else ""
    redacted = redact_snapshot(scanned, RedactionContext(home=home, user="alice"))
    document = json.loads(render_json(redacted))
    assert validate(document) == []
    assert "home_path" in [r["kind"] for r in document["redactions"]]
    assert home not in json.dumps(document)
