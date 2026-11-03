"""Docker Compose project names, container names, ports and mounts (WTS-005)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from tests.fakes import read_fixture
from worktree_shield.models import Policy


def _collect(root: Path, policy: Policy | None = None, directory: str = "") -> Any:
    from worktree_shield.collectors.base import Collected, Scope
    from worktree_shield.collectors.compose import collect_compose

    out = Collected()
    policy = policy or Policy()
    collect_compose(
        Scope(root, "/repos/shop", policy.max_file_bytes), PurePosixPath(directory), policy, out
    )
    return out


def _claims(out: Any) -> set[tuple[str, str, str, int | None]]:
    return {(c.kind.value, c.key, c.source.path, c.source.line) for c in out.claims}


def _unreadable(out: Any) -> set[tuple[str, str, int | None, str]]:
    return {(u.kind.value, u.name, u.source.line, u.reason) for u in out.unreadable}


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    root = tmp_path / "shop-Login"
    root.mkdir()
    for name in ("compose.yaml", "compose.override.yaml"):
        (root / name).write_text(read_fixture("compose", name))
    return root


def test_the_example_project(shop: Path) -> None:
    out = _collect(shop)
    assert _claims(out) == {
        ("compose_project", "compose-project://shop", "compose.yaml", 1),
        ("container_name", "container://shop-web-dev", "compose.override.yaml", 3),
        ("listen_port", "tcp://*:8080", "compose.yaml", 7),
        ("listen_port", "tcp://127.0.0.1:8443", "compose.yaml", 8),
        ("listen_port", "tcp://*:3000", "compose.override.yaml", 5),
        ("absolute_path", "path:///srv/shop/uploads", "compose.yaml", 12),
        ("listen_port", "tcp://*:5432", "compose.yaml", 17),
        ("volume", "volume://shop_pgdata", "compose.yaml", 20),
        ("volume", "volume://shared-cache", "compose.yaml", 21),
    }
    assert _unreadable(out) == {
        (
            "container_name",
            "services.worker.container_name",
            26,
            "depends on WORKER_NAME, which no file that was read sets",
        ),
        (
            "listen_port",
            "services.worker.ports[0]",
            27,
            "depends on METRICS_PORT, which no file that was read sets",
        ),
        ("listen_port", "services.worker.ports[1]", 27, "is not a valid port mapping"),
    }


def test_details_say_what_was_read(shop: Path) -> None:
    details = {c.key: c.detail for c in _collect(shop).claims}
    assert details["compose-project://shop"] == "name: shop"
    assert details["container://shop-web-dev"] == "services.web.container_name: shop-web-dev"
    assert details["tcp://*:8080"] == "services.web.ports: 8080:80"
    assert details["tcp://*:5432"] == "services.db.ports: published 5432"
    assert details["volume://shared-cache"] == "services.db.volumes: shared-cache (external)"


def test_env_file_sets_the_project_name_and_variables(shop: Path) -> None:
    (shop / ".env").write_text("COMPOSE_PROJECT_NAME=Shop_Login\nWEB_PORT=8081\nWORKER_NAME=w1\n")
    keys = {c.key for c in _collect(shop, Policy(include_env_files=True)).claims}
    assert {"compose-project://shop_login", "tcp://*:8081", "volume://shop_login_pgdata"} <= keys
    assert "container://w1" in keys
    assert {c.key for c in _collect(shop).claims} >= {"compose-project://shop"}  # .env not read


def test_without_a_name_the_directory_names_the_project(tmp_path: Path) -> None:
    root = tmp_path / "Shop.Login"
    (root / "infra").mkdir(parents=True)
    (root / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres\n")
    (root / "infra" / "compose.yml").write_text("services:\n  db:\n    image: postgres\n")
    project = {c.key: c.detail for c in _collect(root).claims}
    assert project == {"compose-project://shoplogin": "directory name Shop.Login"}
    infra = {c.key for c in _collect(root, directory="infra").claims}
    assert infra == {"compose-project://infra"}  # the same in every worktree


def test_compose_yaml_wins_over_docker_compose_yml(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("name: new\n")
    (tmp_path / "docker-compose.yml").write_text("name: old\n")
    assert {c.key for c in _collect(tmp_path).claims} == {"compose-project://new"}


def test_the_last_name_wins_across_files_and_documents(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("name: first\n---\nname: second\n")
    (tmp_path / "compose.override.yml").write_text("name: ''\n")
    assert {c.key for c in _collect(tmp_path).claims} == {"compose-project://second"}


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("services: [\n", "is not valid YAML"),
        ("a: " + "[" * 5000 + "]" * 5000 + "\n", "is nested too deeply"),
    ],
)
def test_files_that_cannot_be_read(tmp_path: Path, text: str, reason: str) -> None:
    (tmp_path / "compose.yaml").write_text(text)
    out = _collect(tmp_path)
    assert out.claims == []
    assert [(s.source.path, s.reason) for s in out.skipped] == [("compose.yaml", reason)]


@pytest.mark.parametrize(
    "text",
    [
        "[1, 2]\n",
        "services: [web]\n",
        "services:\n  web: nginx\n",
        "services:\n  web:\n    ports: 8080\n    volumes: /x\n",
        "name: 5\n",
    ],
)
def test_odd_shapes_yield_only_the_project(tmp_path: Path, text: str) -> None:
    (tmp_path / "compose.yaml").write_text(text)
    out = _collect(tmp_path)
    assert {c.kind.value for c in out.claims} <= {"compose_project"}
    assert out.skipped == []


def test_python_tags_are_never_constructed(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("name: !!python/object/apply:os.system ['true']\n")
    out = _collect(tmp_path)
    assert [s.reason for s in out.skipped] == ["is not valid YAML"]


EDGES = """\
x-base: &base
  container_name: from-anchor
services:
  merged:
    <<: *base
  odd:
    container_name: 5
    ports:
      - target: 80
        published: "${NOPE}"
    volumes:
      - ${DATA_DIR}:/data
      - ./data:/data
      - ~/.cache/shop:/cache
      - type: tmpfs
        target: /run/scratch
      - fixed:/fixed
  empty:
    container_name: ""
  invalid:
    container_name: "${}"
volumes:
  fixed:
    name: ${VOLUME_NAME:-shop-shared}
"""


def test_edges(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(EDGES)
    (tmp_path / ".env").write_text("BASE=8000\nWEB=${BASE}\nGONE=${NOPE}\nVOLUME_NAME=${BASE}-v\n")
    out = _collect(tmp_path, Policy(include_env_files=True))
    claims = {(c.key, c.source.line) for c in out.claims}
    assert claims == {
        (f"compose-project://{tmp_path.name.lower()}", None),
        ("container://from-anchor", 2),  # through a merge key: the line of the anchor's value
        ("path://~/.cache/shop", 14),
        ("volume://8000-v", 17),
    }
    assert _unreadable(out) == {
        (
            "listen_port",
            "services.odd.ports[0]",
            9,
            "depends on NOPE, which no file that was read sets",
        ),
        (
            "absolute_path",
            "services.odd.volumes[0]",
            12,
            "depends on DATA_DIR, which no file that was read sets",
        ),
        (
            "container_name",
            "services.invalid.container_name",
            21,
            "has an invalid ${...} reference",
        ),
    }


def test_no_compose_file_and_an_oversized_one(tmp_path: Path) -> None:
    assert _collect(tmp_path).claims == []
    (tmp_path / "compose.yaml").write_text("name: x\n" + "#" * 100 + "\n")
    out = _collect(tmp_path, Policy(max_file_bytes=50))
    assert out.claims == []
    assert [s.reason for s in out.skipped] == ["is larger than 50 bytes"]


def test_lines_of_odd_shapes() -> None:
    import yaml

    from worktree_shield.collectors.compose import _line

    node = yaml.compose("a: 1\nb: [x]\n", Loader=yaml.SafeLoader)
    assert node is not None
    assert _line(node, "a", "b") is None
    assert _line(node, "b", 3) is None
    assert _line(node, "b", 0) == 2


def test_named_pipes_are_no_shared_resource(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(
        "services:\n  ci:\n    volumes:\n"
        "      - type: npipe\n        source: '\\\\.\\pipe\\docker_engine'\n        target: /x\n"
    )
    assert {c.kind.value for c in _collect(tmp_path).claims} == {"compose_project"}
