"""Command-line interface: parses arguments and wires the layers together.

No diagnosis logic lives here; commands call collectors, rules and renderers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from worktree_shield import __version__
from worktree_shield.config import PolicyError, policy_of
from worktree_shield.exit_codes import ExitCode
from worktree_shield.git.discovery import NotARepositoryError
from worktree_shield.orchestrator import inspect_resources, inspect_worktrees
from worktree_shield.privacy import RedactionContext, Redactor, redact_snapshot
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
) -> None:
    """List the ports, databases, Compose names and paths each worktree declares.

    Reads .env templates, package.json, vite.config.*, pyproject.toml and Compose files
    as data; nothing is run and Docker is not contacted. Resources used by more than one
    worktree are marked. Exits with 2 for a policy file that cannot be used and 3 outside
    a Git repository.
    """
    redactor = Redactor(RedactionContext.current())
    try:
        snapshot = inspect_resources(
            SubprocessRunner(), repo, include_env_files=True if include_env else None
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
