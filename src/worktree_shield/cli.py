"""Command-line interface: parses arguments and wires the layers together.

No diagnosis logic lives here; commands call collectors, rules and renderers.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from worktree_shield import __version__
from worktree_shield.config import PolicyError, policy_of
from worktree_shield.exit_codes import ExitCode
from worktree_shield.git.discovery import NotARepositoryError
from worktree_shield.models import Status
from worktree_shield.orchestrator import diagnose, inspect_resources, inspect_worktrees
from worktree_shield.privacy import RedactionContext, Redactor, redact_snapshot
from worktree_shield.reports.findings import render_scan
from worktree_shield.reports.terminal import render_policy, render_resources, render_worktrees
from worktree_shield.runner import SubprocessRunner

HELP = (
    "Audit the worktrees of a Git repository for shared ports, databases and Docker "
    "resources before your agents collide.\n\n"
    "Read-only: nothing in the repository is executed, changed or locked (.git included), "
    "no process is stopped, no container is touched, and secrets are never printed."
)

app = typer.Typer(
    name="worktree-shield",
    help=HELP,
    no_args_is_help=True,
    add_completion=False,
    # Rich tracebacks print local variables, which can hold environment values.
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"worktree-shield {__version__}")
        raise typer.Exit()


@app.callback()
def cli(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Global options (the help text comes from HELP)."""


class Scope(StrEnum):
    ALL = "all"
    STATIC = "static"
    RUNTIME = "runtime"


_RUNTIME_RULES = frozenset({"WTS-PORT-002", "WTS-RUNTIME-001"})
_REPO_OPTION = typer.Option(
    "--repo", metavar="PATH", help="A directory inside the repository (default: here)."
)
_ENV_OPTION = typer.Option(
    "--include-env",
    help="Also read .env and .env.local; only ports, database servers and paths are kept.",
)


@app.command()
def scan(
    repo: Annotated[Path, _REPO_OPTION] = Path(),
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Exit with 1 when a finding fails under the policy."),
    ] = False,
    scope: Annotated[
        Scope,
        typer.Option(
            "--scope",
            help="all: configuration and running processes; static: configuration only; "
            "runtime: only what running processes show.",
        ),
    ] = Scope.ALL,
    include_env: Annotated[bool, _ENV_OPTION] = False,
    show_all: Annotated[
        bool, typer.Option("--all", help="Also list the checks that passed or did not apply.")
    ] = False,
) -> None:
    """Find ports, databases, Compose names and paths the worktrees share.

    Reads configuration as data and, unless --scope static, looks at listening
    processes; nothing is run, changed or locked. Exit codes: 0 when the scan ran, 1
    with --strict when a finding fails under the policy, 2 for errors, 3 outside a Git
    repository.
    """
    redactor = Redactor(RedactionContext.current())
    try:
        snapshot = inspect_resources(
            SubprocessRunner(),
            repo,
            include_env_files=True if include_env else None,
            include_runtime=False if scope is Scope.STATIC else None,
        )
    except NotARepositoryError:
        typer.echo(f"worktree-shield: {repo} is not inside a Git repository", err=True)
        raise typer.Exit(ExitCode.CONTEXT_UNAVAILABLE) from None
    except PolicyError as error:
        typer.echo(f"worktree-shield: {redactor.text(str(error))}", err=True)
        raise typer.Exit(ExitCode.ERROR) from None
    diagnosed = diagnose(snapshot)
    if scope is Scope.RUNTIME:
        kept = tuple(f for f in diagnosed.findings if f.id in _RUNTIME_RULES)
        diagnosed = dataclasses.replace(diagnosed, findings=kept)
    render_scan(redact_snapshot(diagnosed), Console(highlight=False), show_all=show_all)
    if diagnosed.repository is None:
        raise typer.Exit(ExitCode.ERROR)
    if strict and any(f.status is Status.FAIL for f in diagnosed.findings):
        raise typer.Exit(ExitCode.STRICT_FAILURE)


@app.command()
def worktrees(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo", metavar="PATH", help="A directory inside the repository (default: here)."
        ),
    ] = Path(),
) -> None:
    """List the worktrees of the repository, as Git records them.

    Runs only git rev-parse and git worktree list, with optional locks off: nothing in
    .git is written. Exits with code 3 when PATH is not inside a Git repository.
    """
    try:
        snapshot = inspect_worktrees(SubprocessRunner(), repo)
    except NotARepositoryError:
        typer.echo(f"worktree-shield: {repo} is not inside a Git repository", err=True)
        raise typer.Exit(ExitCode.CONTEXT_UNAVAILABLE) from None
    render_worktrees(redact_snapshot(snapshot), Console(highlight=False))
    if snapshot.repository is None:
        raise typer.Exit(ExitCode.ERROR)


@app.command()
def policy(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo", metavar="PATH", help="A directory inside the repository (default: here)."
        ),
    ] = Path(),
) -> None:
    """Show the policy that applies: .worktree-shield.toml in this worktree, or the defaults.

    The file is read as data, never run. A file that cannot be used is reported with the
    key at fault and exits with code 2; outside a Git repository the exit code is 3.
    """
    redactor = Redactor(RedactionContext.current())
    try:
        snapshot = inspect_worktrees(SubprocessRunner(), repo)
        if snapshot.repository is None:
            details = "; ".join(f.detail for f in snapshot.probe_failures)
            raise PolicyError(f"the worktrees could not be listed: {details}")
        effective = policy_of(snapshot.repository)
    except NotARepositoryError:
        typer.echo(f"worktree-shield: {repo} is not inside a Git repository", err=True)
        raise typer.Exit(ExitCode.CONTEXT_UNAVAILABLE) from None
    except PolicyError as error:
        typer.echo(f"worktree-shield: {redactor.text(str(error))}", err=True)
        raise typer.Exit(ExitCode.ERROR) from None
    current = snapshot.repository.current
    render_policy(
        redactor.redact(effective),
        redactor.text(current) if current is not None else None,
        Console(highlight=False),
    )


@app.command()
def resources(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo", metavar="PATH", help="A directory inside the repository (default: here)."
        ),
    ] = Path(),
    include_env: Annotated[
        bool,
        typer.Option(
            "--include-env",
            help="Also read .env and .env.local; only ports, database servers and paths are kept.",
        ),
    ] = False,
    no_runtime: Annotated[
        bool,
        typer.Option(
            "--no-runtime",
            help="Do not look at running processes (their sockets and working directories).",
        ),
    ] = False,
) -> None:
    """List the ports, databases, Compose names and paths each worktree declares.

    Reads .env templates, package.json, vite.config.*, pyproject.toml and Compose files
    as data; nothing is run and Docker is not contacted. Listening processes count for
    the worktree they run in. Resources used by more than one worktree are marked.
    Exits with 2 for a policy file that cannot be used and 3 outside a Git repository.
    """
    redactor = Redactor(RedactionContext.current())
    try:
        snapshot = inspect_resources(
            SubprocessRunner(),
            repo,
            include_env_files=True if include_env else None,
            include_runtime=False if no_runtime else None,
        )
    except NotARepositoryError:
        typer.echo(f"worktree-shield: {repo} is not inside a Git repository", err=True)
        raise typer.Exit(ExitCode.CONTEXT_UNAVAILABLE) from None
    except PolicyError as error:
        typer.echo(f"worktree-shield: {redactor.text(str(error))}", err=True)
        raise typer.Exit(ExitCode.ERROR) from None
    render_resources(redact_snapshot(snapshot), Console(highlight=False))
    if snapshot.repository is None:
        raise typer.Exit(ExitCode.ERROR)


def main() -> None:
    """Console entry point.

    Typer reports usage errors itself (exit code 2) and turns Ctrl+C into 130. Anything
    else that escapes is a bug: print one redacted line instead of a traceback, which
    could contain local values, and exit with 2. ``WTS_DEBUG=1`` shows the traceback.
    """
    try:
        app()
    except Exception as exc:  # SystemExit (normal exits) is not an Exception
        if os.environ.get("WTS_DEBUG"):
            raise
        message = Redactor(RedactionContext.current()).text(str(exc)) or type(exc).__name__
        typer.echo(
            f"worktree-shield: internal error: {message}\n"
            "Run it again with WTS_DEBUG=1 to see the traceback, and please report it.",
            err=True,
        )
        sys.exit(ExitCode.ERROR)
