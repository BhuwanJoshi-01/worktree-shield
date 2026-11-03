"""Docker Compose: project names, container names, published ports and mounts.

Files are chosen as compose-go chooses them: the first of :data:`COMPOSE_FILES` in a
directory, plus the first of :data:`OVERRIDE_FILES` next to it. They are loaded with
``yaml.SafeLoader`` (pure Python: deep nesting raises ``RecursionError`` instead of
overflowing the C stack), which builds only plain data. Nothing is passed to Docker.

The project name follows compose-go's precedence: ``COMPOSE_PROJECT_NAME`` (from
``.env``, when env files are read), then the last non-empty ``name:``, then the name of
the directory, normalised. It prefixes containers, networks and named volumes, so two
worktrees with the same project name share all of them; a ``name:`` in the file, or a
compose file in a subdirectory such as ``infra/``, gives every worktree the same one.

Overrides are merged the simple way: a service's ``container_name`` is the last one
set; ports and volumes of all files are listed together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from worktree_shield.collectors.base import (
    Collected,
    Scope,
    is_absolute_path,
    path_key,
    port_key,
)
from worktree_shield.models import (
    Policy,
    ResourceClaim,
    ResourceKind,
    SkippedFile,
    SourceRef,
    UnreadableValue,
)
from worktree_shield.parsers.compose import parse_mount, published_ports
from worktree_shield.parsers.dotenv import parse_dotenv
from worktree_shield.parsers.interpolate import Interpolated, interpolate

COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")
OVERRIDE_FILES = (
    "compose.override.yml",
    "compose.override.yaml",
    "docker-compose.override.yml",
    "docker-compose.override.yaml",
)
_PROJECT_CHARS = re.compile(r"[a-z0-9_-]")


def normalize_project_name(name: str) -> str:
    """compose-go's NormalizeProjectName: lower case, ``[a-z0-9_-]`` only, no leading
    ``_`` or ``-``."""
    return "".join(_PROJECT_CHARS.findall(name.lower())).lstrip("_-")


@dataclass
class _Document:
    relative: PurePosixPath
    node: yaml.Node
    data: Any


@dataclass
class _Service:
    container_name: tuple[_Document, Any] | None = None
    ports: list[tuple[_Document, int, Any]] = field(default_factory=list)
    volumes: list[tuple[_Document, int, Any]] = field(default_factory=list)


def collect_compose(scope: Scope, directory: PurePosixPath, policy: Policy, out: Collected) -> None:
    """The Compose resources of the project in ``directory``, if it has one."""
    main = _first(scope, directory, COMPOSE_FILES)
    if main is None:
        return
    documents = _load(scope, directory / main, out)
    if documents is None:
        return  # unreadable (recorded as skipped): even the project name is unknown
    override = _first(scope, directory, OVERRIDE_FILES)
    if override is not None:
        documents += _load(scope, directory / override, out) or []
    variables = _env_variables(scope, directory, out) if policy.include_env_files else {}
    project, source, detail = _project(scope, directory, main, documents, variables)
    out.claims.append(
        ResourceClaim(
            ResourceKind.COMPOSE_PROJECT,
            f"compose-project://{project}",
            scope.worktree,
            source,
            detail,
        )
    )
    _Project(scope, project, variables, documents, out).collect()


def _first(scope: Scope, directory: PurePosixPath, names: tuple[str, ...]) -> str | None:
    folder = Path(scope.root, *directory.parts)
    return next((name for name in names if (folder / name).is_file()), None)


def _load(scope: Scope, relative: PurePosixPath, out: Collected) -> list[_Document] | None:
    """Every YAML document of a file, as nodes (for lines) and plain data; ``None``
    when the file could not be read (recorded in ``out.skipped``)."""
    text = scope.read(relative, out)
    if text is None:
        return None
    documents: list[_Document] = []
    loader = yaml.SafeLoader(text)
    try:
        while loader.check_node():  # also consumes the stream start get_node() expects
            node = loader.get_node()
            if node is None:  # pragma: no cover - check_node() promised a document
                break
            documents.append(_Document(relative, node, loader.construct_document(node)))
    except yaml.YAMLError:
        out.skipped.append(SkippedFile(scope.source(relative), "is not valid YAML"))
        return None
    except RecursionError:
        out.skipped.append(SkippedFile(scope.source(relative), "is nested too deeply"))
        return None
    finally:
        loader.dispose()
    return documents


def _env_variables(scope: Scope, directory: PurePosixPath, out: Collected) -> dict[str, str]:
    """The variables of ``.env`` next to the compose file, which Compose reads for
    interpolation; references to earlier variables are resolved as Compose does."""
    text = scope.read(directory / ".env", out)
    variables: dict[str, str] = {}
    for entry in parse_dotenv(text or ""):
        if not entry.reference:
            variables[entry.key] = entry.value
            continue
        resolved = interpolate(entry.value, variables)
        if resolved.value is not None:
            variables[entry.key] = resolved.value
    return variables


def _project(
    scope: Scope,
    directory: PurePosixPath,
    first_file: str,
    documents: list[_Document],
    variables: dict[str, str],
) -> tuple[str, SourceRef, str]:
    """The project name, where it comes from and how to describe it."""
    from_env = variables.get("COMPOSE_PROJECT_NAME", "")
    if from_env:
        source = scope.source(directory / ".env")
        return normalize_project_name(from_env), source, f"COMPOSE_PROJECT_NAME={from_env} (.env)"
    named: tuple[str, _Document] | None = None
    for document in documents:
        if isinstance(document.data, dict) and isinstance(document.data.get("name"), str):
            value = interpolate(document.data["name"], variables).value
            if value:
                named = (value, document)
    if named is not None:
        value, document = named
        source = scope.source(document.relative, _line(document.node, "name"))
        return normalize_project_name(value), source, f"name: {value}"
    folder = Path(scope.root, *directory.parts).name
    return (
        normalize_project_name(folder),
        scope.source(directory / first_file),
        f"directory name {folder}",
    )


class _Project:
    def __init__(
        self,
        scope: Scope,
        project: str,
        variables: dict[str, str],
        documents: list[_Document],
        out: Collected,
    ) -> None:
        self.scope, self.project, self.variables = scope, project, variables
        self.documents, self.out = documents, out

    def collect(self) -> None:
        services: dict[str, _Service] = {}
        volumes: dict[str, Any] = {}
        for document in self.documents:
            data = document.data if isinstance(document.data, dict) else {}
            if isinstance(data.get("volumes"), dict):
                volumes.update(data["volumes"])
            entries = data.get("services")
            if not isinstance(entries, dict):
                continue
            for name, service in entries.items():
                if not isinstance(name, str) or not isinstance(service, dict):
                    continue
                merged = services.setdefault(name, _Service())
                if "container_name" in service:
                    merged.container_name = (document, service["container_name"])
                for key, target in (("ports", merged.ports), ("volumes", merged.volumes)):
                    if isinstance(service.get(key), list):
                        target.extend((document, i, e) for i, e in enumerate(service[key]))
        for name, service in services.items():
            if service.container_name is not None:
                self.container_name(name, *service.container_name)
            for document, index, entry in service.ports:
                self.port(name, document, index, entry)
            for document, index, entry in service.volumes:
                self.mount(name, document, index, entry, volumes)

    def claim(self, kind: ResourceKind, key: str, source: SourceRef, detail: str) -> None:
        self.out.claims.append(ResourceClaim(kind, key, self.scope.worktree, source, detail))

    def unreadable(self, kind: ResourceKind, name: str, source: SourceRef, reason: str) -> None:
        self.out.unreadable.append(UnreadableValue(kind, source, name, reason))

    def resolve(self, value: Any) -> tuple[Any, str | None]:
        """The value with its variables filled in, or ``None`` and the reason why not.
        Strings inside a long-syntax mapping are filled in too."""
        if isinstance(value, str):
            result = interpolate(value, self.variables)
            return (result.value, None) if result.value is not None else (None, _why(result))
        if isinstance(value, dict):
            resolved: dict[Any, Any] = {}
            for key, item in value.items():
                item_value, reason = self.resolve(item)
                if reason is not None:
                    return None, reason
                resolved[key] = item_value
            return resolved, None
        return value, None

    def source(self, document: _Document, *path: str | int) -> SourceRef:
        return self.scope.source(document.relative, _line(document.node, "services", *path))

    def container_name(self, service: str, document: _Document, value: Any) -> None:
        source = self.source(document, service, "container_name")
        label = f"services.{service}.container_name"
        name, reason = self.resolve(value)
        if reason is not None:
            self.unreadable(ResourceKind.CONTAINER_NAME, label, source, reason)
        elif isinstance(name, str) and name:
            key = f"container://{name}"
            self.claim(ResourceKind.CONTAINER_NAME, key, source, f"{label}: {name}")

    def port(self, service: str, document: _Document, index: int, entry: Any) -> None:
        source = self.source(document, service, "ports", index)
        label = f"services.{service}.ports"
        value, reason = self.resolve(entry)
        ports = published_ports(value) if reason is None else None
        if ports is None:
            why = reason or "is not a valid port mapping"
            self.unreadable(ResourceKind.LISTEN_PORT, f"{label}[{index}]", source, why)
            return
        shown = f"published {value.get('published')}" if isinstance(value, dict) else str(value)
        for port in ports:
            key = port_key(port.host_ip, port.port, protocol=port.protocol)
            self.claim(ResourceKind.LISTEN_PORT, key, source, f"{label}: {shown}")

    def mount(
        self, service: str, document: _Document, index: int, entry: Any, volumes: dict[str, Any]
    ) -> None:
        source = self.source(document, service, "volumes", index)
        label = f"services.{service}.volumes"
        value, reason = self.resolve(entry)
        if reason is not None:  # ${DATA_DIR}:/data: a host path nobody can tell
            self.unreadable(ResourceKind.ABSOLUTE_PATH, f"{label}[{index}]", source, reason)
            return
        mount = parse_mount(value)
        if mount is None or mount.read_only or mount.source is None:
            return  # read-only sharing is no collision; anonymous volumes are per container
        if mount.kind == "bind":
            if mount.source.startswith("~") or is_absolute_path(mount.source):
                key = path_key(mount.source)
                self.claim(ResourceKind.ABSOLUTE_PATH, key, source, f"{label}: {mount.source}")
            return
        if mount.kind != "volume":
            return
        settings = volumes.get(mount.source)
        settings = settings if isinstance(settings, dict) else {}
        fixed = settings.get("name")
        external = settings.get("external") is True
        if isinstance(fixed, str) and fixed:
            name = interpolate(fixed, self.variables).value or fixed
        elif external:
            name = mount.source
        else:
            name = f"{self.project}_{mount.source}"
        detail = f"{label}: {mount.source}" + (" (external)" if external else "")
        self.claim(ResourceKind.VOLUME, f"volume://{name}", source, detail)


def _why(result: Interpolated) -> str:
    if result.missing:
        return f"depends on {', '.join(result.missing)}, which no file that was read sets"
    return "has an invalid ${...} reference"


def _line(node: yaml.Node, *path: str | int) -> int | None:
    """The line of the value at ``path`` in a node tree, or ``None`` if not found."""
    for step in path:
        found: yaml.Node | None = None
        if isinstance(node, yaml.MappingNode) and isinstance(step, str):
            pairs = ((k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode))
            found = next((v for k, v in pairs if k.value == step), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(step, int):
            found = node.value[step] if step < len(node.value) else None
        if found is None:
            return None  # reached through a merge key or an odd shape
        node = found
    return node.start_mark.line + 1
