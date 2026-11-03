"""A plan of changes that would resolve the collisions; worktree-shield applies none.

For every finding that needs attention, the current worktree (or the first one) keeps
its value and each other worktree gets its own: the next port that no worktree
configures and no process holds, a database name with the worktree's name appended,
the worktree's name as its Compose project. A value read from a committed ``.env``
template is overridden in that worktree's own ``.env``, since editing the template
would change it for every branch; values in other files are changed in place.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from worktree_shield.collectors.envfiles import TEMPLATE_FILES
from worktree_shield.models import Evidence, Finding, ResourceKind, Snapshot, Status
from worktree_shield.rules.common import name_of, port_of

_PROBLEMS = (Status.FAIL, Status.WARN)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """In ``worktree``, at ``where`` (a file, with a line when known), make ``change``."""

    worktree: str
    where: str
    change: str
    rule: str


def make_plan(snapshot: Snapshot) -> list[Suggestion]:
    """The suggested changes, in finding order; empty when nothing needs attention."""
    repository = snapshot.repository
    if repository is None:
        return []
    order = [w.path for w in repository.worktrees]
    current = repository.current
    taken = {p for c in snapshot.claims if (p := port_of(c.key)) is not None}
    if snapshot.runtime is not None:
        taken |= {listener.port for listener in snapshot.runtime.unattributed}
    planner = _Planner(order, current, taken)
    suggestions: list[Suggestion] = []
    for finding in snapshot.findings:
        if finding.status in _PROBLEMS and finding.caused_by is None:
            suggestions += planner.suggest(finding)
    return suggestions


class _Planner:
    def __init__(self, order: list[str], current: str | None, taken: set[int]) -> None:
        self.rank = {worktree: index for index, worktree in enumerate(order)}
        self.current, self.taken = current, taken
        self.assigned: dict[tuple[str, int], int] = {}  # (worktree, old port) -> new port
        self.seen: set[tuple[str, str, str]] = set()

    def movers(self, finding: Finding) -> list[str]:
        """The worktrees that change: all but the one that keeps the value, by path, so
        the result does not depend on the order Git lists them in."""
        involved = sorted(finding.worktrees, key=lambda w: self.rank.get(w, len(self.rank)))
        if finding.id == "WTS-PORT-002" and not finding.summary.endswith("another worktree"):
            return sorted(involved)  # a process outside the worktrees holds it: all move
        keeper = self.current if self.current in involved else involved[0]
        return sorted(w for w in involved if w != keeper)

    def new_port(self, worktree: str, old: int) -> int:
        """One new port per worktree and old port, however many findings name it."""
        if (worktree, old) not in self.assigned:
            port = old + 1
            while port in self.taken:
                port += 1
            self.taken.add(port)
            self.assigned[(worktree, old)] = port
        return self.assigned[(worktree, old)]

    def suggest(self, finding: Finding) -> Iterator[Suggestion]:
        for suggestion in self._suggest(finding):
            key = (suggestion.worktree, suggestion.where, suggestion.change)
            if key not in self.seen:
                self.seen.add(key)
                yield suggestion

    def _suggest(self, finding: Finding) -> Iterator[Suggestion]:
        kind = _KIND_OF.get(finding.id)
        if kind is None or finding.resource_key is None:
            return
        key = finding.resource_key
        for position, worktree in enumerate(self.movers(finding), start=1):
            items = [
                e for e in finding.evidence if e.key == worktree and not e.source.startswith("pid ")
            ]
            if kind is ResourceKind.LISTEN_PORT:
                old = port_of(key) or 0
                new = self.new_port(worktree, old)
                for item in items:
                    yield _port(finding, worktree, item, old, new)
            elif kind is ResourceKind.DATABASE:
                new_name, database = _database(key, worktree, position)
                for item in items:
                    where = _env_override(item) or item.source
                    change = f"{item.value} naming the database {new_name} instead of {database}"
                    yield Suggestion(worktree, where, change, finding.id)
            elif kind is ResourceKind.COMPOSE_PROJECT:
                for item in items[:1]:
                    folder = PurePosixPath(item.source.split(":", 1)[0]).parent
                    change = f"COMPOSE_PROJECT_NAME={_slug(worktree, '-')}"
                    yield Suggestion(worktree, (folder / ".env").as_posix(), change, finding.id)
            elif kind is ResourceKind.CONTAINER_NAME:
                change = (
                    f"container_name: remove it, or use ${{COMPOSE_PROJECT_NAME}}-{name_of(key)}"
                )
                for item in items:
                    yield Suggestion(worktree, item.source, change, finding.id)
            else:  # volumes and paths: a name of their own
                yield from _renamed(finding, worktree, items)


def _port(finding: Finding, worktree: str, item: Evidence, old: int, new: int) -> Suggestion:
    detail = item.value or ""
    override = _env_override(item)
    if override is not None:  # PORT=5173 from .env.example: PORT=5174 in .env
        variable = detail.split("=", 1)[0]
        return Suggestion(worktree, override, f"{variable}={new}", finding.id)
    if detail.startswith(("scripts.", "tool.")) and ": " in detail:
        detail = detail.split(": ", 1)[1]  # the fragment, not the task name
    # The first number is the host port: in "5432:5432" the container's stays.
    changed = detail.replace(str(old), str(new), 1) if str(old) in detail else f"port {new}"
    return Suggestion(worktree, item.source, f"{detail} → {changed}", finding.id)


def _database(key: str, worktree: str, position: int) -> tuple[str, str]:
    """(new name, old name); Redis databases are numbers, so the next free ones."""
    engine = name_of(key).split("/", 1)[0]
    database = name_of(key).rsplit("/", 1)[-1]
    if engine == "redis" and database.isdigit():
        return str(int(database) + position), database
    return f"{database}_{_slug(worktree, '_')}", database


def _renamed(finding: Finding, worktree: str, items: list[Evidence]) -> Iterator[Suggestion]:
    name = name_of(finding.resource_key or "")
    renamed = f"{name}-{_slug(worktree, '-')}"
    for item in items:
        override = _env_override(item)
        if override is not None:  # UPLOAD_DIR=… from a template
            variable = (item.value or "").split("=", 1)[0]
            yield Suggestion(worktree, override, f"{variable}={renamed}", finding.id)
        else:
            yield Suggestion(worktree, item.source, f"{name} → {renamed}", finding.id)


_KIND_OF = {
    "WTS-PORT-001": ResourceKind.LISTEN_PORT,
    "WTS-PORT-002": ResourceKind.LISTEN_PORT,
    "WTS-DB-001": ResourceKind.DATABASE,
    "WTS-DOCKER-001": ResourceKind.COMPOSE_PROJECT,
    "WTS-DOCKER-002": ResourceKind.CONTAINER_NAME,
    "WTS-DOCKER-003": ResourceKind.VOLUME,
    "WTS-PATH-001": ResourceKind.ABSOLUTE_PATH,
}


def _env_override(item: Evidence) -> str | None:
    """``apps/web/.env`` for a claim read from ``apps/web/.env.example``."""
    path = PurePosixPath(item.source.split(":", 1)[0])
    return (path.parent / ".env").as_posix() if path.name in TEMPLATE_FILES else None


def _slug(worktree: str, separator: str) -> str:
    """The worktree's directory name, as an identifier: ``app-login`` / ``app_login``."""
    name = PurePosixPath(worktree.replace("\\", "/")).name.lower()
    return re.sub(r"[^a-z0-9]+", separator, name).strip(separator) or "worktree"
