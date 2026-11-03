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
from worktree_shield.models import Snapshot, Status
from worktree_shield.orchestrator import diagnose, inspect_resources, inspect_worktrees
from worktree_shield.plan import make_plan
from worktree_shield.privacy import RedactionContext, Redactor, redact_snapshot
from worktree_shield.reports.findings import render_plan, render_scan
from worktree_shield.reports.json_report import render_json
from worktree_shield.reports.markdown import render_markdown
from worktree_shield.reports.sarif import render_sarif
from worktree_shield.reports.terminal import render_policy, render_resources, render_worktrees
from worktree_shield.rules.catalog import builtin_rules
from worktree_shield.rules.explain import explanation
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


class Format(StrEnum):
    TERMINAL = "terminal"
    JSON = "json"
    MARKDOWN = "markdown"
    SARIF = "sarif"


class ReportFormat(StrEnum):
    MARKDOWN = "markdown"
    JSON = "json"
    SARIF = "sarif"


_STRICT_OPTION = typer.Option("--strict", help="Exit with 1 when a finding fails under the policy.")
_SCOPE_OPTION = typer.Option(
    "--scope",
    help="all: configuration and running processes; static: configuration only; "
    "runtime: only what running processes show.",
)


def _diagnosed(repo: Path, scope: Scope, include_env: bool) -> Snapshot:
    """Scan and diagnose, or exit with 3 (not a repository) or 2 (unusable policy)."""
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
        message = Redactor(RedactionContext.current()).text(str(error))
        typer.echo(f"worktree-shield: {message}", err=True)
        raise typer.Exit(ExitCode.ERROR) from None
    diagnosed = diagnose(snapshot)
    if scope is Scope.RUNTIME:
        kept = tuple(f for f in diagnosed.findings if f.id in _RUNTIME_RULES)
        diagnosed = dataclasses.replace(diagnosed, findings=kept)
    return diagnosed


def _rendered(snapshot: Snapshot, output_format: str) -> str:
    if output_format == Format.JSON:
        return render_json(snapshot)
    if output_format == Format.SARIF:
        return render_sarif(snapshot)
    return render_markdown(snapshot)


def _finish(diagnosed: Snapshot, strict: bool) -> None:
    if diagnosed.repository is None:
        raise typer.Exit(ExitCode.ERROR)
    if strict and any(f.status is Status.FAIL for f in diagnosed.findings):
        raise typer.Exit(ExitCode.STRICT_FAILURE)


@app.command()
def scan(
    repo: Annotated[Path, _REPO_OPTION] = Path(),
    strict: Annotated[bool, _STRICT_OPTION] = False,
    scope: Annotated[Scope, _SCOPE_OPTION] = Scope.ALL,
    include_env: Annotated[bool, _ENV_OPTION] = False,
    output_format: Annotated[
        Format, typer.Option("--format", help="terminal, or json/markdown/sarif on stdout.")
    ] = Format.TERMINAL,
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
    diagnosed = _diagnosed(repo, scope, include_env)
    redacted = redact_snapshot(diagnosed)
    if output_format is Format.TERMINAL:
        render_scan(redacted, Console(highlight=False), show_all=show_all)
    else:
        sys.stdout.write(_rendered(redacted, output_format))
    _finish(diagnosed, strict)


@app.command()
def report(
    repo: Annotated[Path, _REPO_OPTION] = Path(),
    output_format: Annotated[
        ReportFormat, typer.Option("--format", "-f", help="markdown, json or sarif.")
    ] = ReportFormat.MARKDOWN,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", metavar="FILE", help="Write to FILE (default: stdout)."),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite FILE if it exists.")] = False,
    strict: Annotated[bool, _STRICT_OPTION] = False,
    scope: Annotated[Scope, _SCOPE_OPTION] = Scope.ALL,
    include_env: Annotated[bool, _ENV_OPTION] = False,
) -> None:
    """Write the scan as a shareable report: Markdown for an issue or PR, JSON for
    scripts, SARIF for code scanning.

    The report is redacted (home paths, user names, secrets). The file named with
    --output is the only thing worktree-shield ever writes.
    """
    to_file = output is not None and str(output) != "-"
    if to_file and output is not None and output.exists() and not force:
        typer.echo(f"worktree-shield: {output} exists; use --force to overwrite it.", err=True)
        raise typer.Exit(ExitCode.ERROR)
    diagnosed = _diagnosed(repo, scope, include_env)
    redacted = redact_snapshot(diagnosed)
    rendered = _rendered(redacted, output_format)
    if to_file and output is not None:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output}. Read it before you share it.", err=True)
    else:
        sys.stdout.write(rendered)
    _finish(diagnosed, strict)


@app.command()
def plan(
    repo: Annotated[Path, _REPO_OPTION] = Path(),
    scope: Annotated[Scope, _SCOPE_OPTION] = Scope.ALL,
    include_env: Annotated[bool, _ENV_OPTION] = False,
) -> None:
    """Suggest a change per worktree that would resolve each collision; apply none.

    The current worktree keeps its values; every other one gets a free port, its own
    database and Compose project name. Values from .env templates are overridden in
    the worktree's .env. Nothing is written.
    """
    diagnosed = _diagnosed(repo, scope, include_env)
    redacted = redact_snapshot(diagnosed)
    render_plan(redacted, make_plan(redacted), Console(highlight=False))
    if diagnosed.repository is None:
        raise typer.Exit(ExitCode.ERROR)


@app.command()
def explain(
    rule_id: Annotated[str, typer.Argument(metavar="RULE", help="A rule ID such as WTS-PORT-001.")],
) -> None:
    """Explain a rule: what it finds, which policy key decides it, how to fix it."""
    text = explanation(rule_id)
    if text is None:
        typer.echo(
            f"worktree-shield: no rule {rule_id}; worktree-shield rules lists them", err=True
        )
        raise typer.Exit(ExitCode.ERROR)
    sys.stdout.write(text)


@app.command(name="rules")
def list_rules() -> None:
    """List every rule with its ID; worktree-shield explain RULE says more."""
    for rule in builtin_rules():
        typer.echo(f"{rule.id:<16} {rule.title}")


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
