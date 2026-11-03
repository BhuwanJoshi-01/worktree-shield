# AGENTS.md

Guide for contributors and coding agents. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the rules in full.

## What this is

A read-only Python CLI that audits the existing worktrees of a Git repository for shared resources: listen
ports, database targets, Docker Compose project and container names, absolute mutable paths. Plain Python 3.11+,
Typer and Rich, packaged with uv (`uv_build` backend), `src/` layout. Commands: `worktree-shield`, alias
`wtshield`.

## Commands

```bash
uv sync                                    # create .venv with the dev tools
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q   # what CI runs
uv run pytest -q --cov                     # with coverage
```

## Layout

```
src/worktree_shield/
  cli.py          Typer app + main(): exit codes, redacted internal errors (WTS_DEBUG=1 for tracebacks)
  models.py       Status/Severity/Confidence, Certainty (confirmed/probable/possible/unknown), SourceRef,
                  Evidence, Finding (codes WTS-<AREA>-<NNN>), ProbeFailure, Policy/PolicyLevel, Snapshot
  runner.py       CommandRunner protocol, SubprocessRunner (no shell, timeout kills the process group,
                  capped output), probe_failure()
  privacy.py      strip_control(), RedactionContext, Redactor, redact_snapshot()
  exit_codes.py   ExitCode: 0 ok, 1 strict, 2 error, 3 not in a Git repository, 130 interrupted
  orchestrator.py inspect_worktrees(): runs discovery, builds the Snapshot (facts only)
  config.py       .worktree-shield.toml: parse_policy() (tomllib, every key checked, unknown = error),
                  load_policy() (regular file inside the worktree, 64 KiB cap), apply_overrides()
  git/            porcelain.py (parse `worktree list --porcelain -z`), discovery.py (git_argv: -c
                  core.fsmonitor=false -C DIR; GIT_ENV: optional locks off, no prompt, LC_ALL=C)
  reports/        terminal.py (plain Text; display_path() escapes control characters)
tests/
  conftest.py     autouse no_network guard (UNIX sockets allowed); HYPOTHESIS_PROFILE=thorough
  fakes.py        FakeRunner: scripted commands only, anything else fails the test
  gitrepos.py     real repositories in tmp dirs (make_repo, add_worktree; global git config off),
                  tree_digest() to prove a scan wrote nothing, same_path() for Windows paths
  fixtures/git/   real porcelain captures (binary in .gitattributes: NULs and a newline in a path)
  fixtures/policy/ hand-written policy files
  unit/           unit tests; Git fixtures are real temporary repositories
docs/roadmap.md   requirement IDs WTS-001 … and what v0.1 includes
docs/policy.md    every key of .worktree-shield.toml, levels, precedence, what makes a file invalid
.github/          CI, issue forms, PR template
```

The core (runner, privacy, models, CLI shell) follows gpu-stack-inspector and screenshare-doctor; each project
keeps its own copy on purpose.

## Rules that are easy to break

- **Never execute anything from the scanned repository**: no scripts, hooks, Vite configs, Compose, Python or
  shell. Parse config as data with byte limits; don't follow symlinks out of the repository.
- **Read-only, `.git` included.** Run git as `GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0 git -c core.fsmonitor=false
  …`. Never `prune`, `kill`, `docker`, `createdb`/`dropdb` or rewrite `.env`.
- **Drop credentials on parse.** DB URLs become scheme/host/port/database immediately; passwords never reach a
  model, a log or any output (terminal, JSON, Markdown, SARIF).
- `.env` and `.env.local` only with explicit opt-in; `.env.example`/`.env.template` are fine.
- Subprocesses: argument lists only (no `shell=True`), always a timeout and an output cap, always through the
  command runner.
- Listen ports and client endpoints are different resource kinds; shared Postgres at 5432 is not a bind collision.
- Static evidence gives *probable* at most; *confirmed* needs a running process attributed by its working
  directory. When in doubt, `unknown`.
- Tests first where possible: `@pytest.mark.xfail(strict=True, reason="WTS-0xx")`, then implement and drop the
  marker.

## Commits

One logical change per commit; imperative subject of at most 72 characters; a body that explains why; a
`Refs: WTS-0xx` trailer when a requirement applies. Every commit passes the CI command above.
