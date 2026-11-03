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
                  Evidence, Finding (codes WTS-<AREA>-<NNN>), ProbeFailure, Policy/PolicyLevel,
                  ResourceKind (listen_port vs client_endpoint …), ResourceClaim, SkippedFile,
                  UnreadableValue, Collision, Snapshot
  runner.py       CommandRunner protocol, SubprocessRunner (no shell, timeout kills the process group,
                  capped output), probe_failure()
  privacy.py      strip_control(), RedactionContext, Redactor, redact_snapshot()
  exit_codes.py   ExitCode: 0 ok, 1 strict, 2 error, 3 not in a Git repository, 130 interrupted
  overlap.py      overlap(kind, a, b) -> same/possible/none: */0.0.0.0/:: wildcards (dual-stack),
                  localhost vs addresses, loopback DB servers, normalised and nested paths
  plan.py         make_plan(): suggestions only (the current worktree keeps its values; one
                  new port per worktree and old port; .env overrides for template values)
  collisions.py   find_collisions(claims): connected components over overlap(), more than one
                  worktree; certainty confirmed (runtime) / probable / possible; reasons
  orchestrator.py inspect_worktrees(), inspect_resources(): discovery + policy + static
                  collectors + runtime over every worktree with files (facts only); diagnose()
                  adds the findings of every rule
  config.py       .worktree-shield.toml: parse_policy() (tomllib, every key checked, unknown = error),
                  load_policy() (regular file inside the worktree, 64 KiB cap), apply_overrides()
  files.py        read_inside(): THE way to read a worktree file (stays inside the worktree, regular
                  files only, O_NONBLOCK + fstat, refused over the cap, never cut); RefusedError
  names.py        what variable names mean (PORT vs DB_PORT, mutable path or not), literal hosts
  parsers/        pure text parsers: dotenv.py (no expansion; references marked; values not in
                  repr), dburl.py (engine/host/port/database; credentials dropped; uncertain
                  host = DatabaseURLError, which never repeats the URL), commands.py (listen
                  ports in script command lines; clients skipped; fragment only), jstext.py
                  (JS with comments/strings/regexes blanked, positions kept), interpolate.py
                  (Compose ${VAR:-x}; unset = assumed, needed without default = missing),
                  compose.py (ports/volumes syntax)
  collectors/     base.py (Scope: root + worktree name + cap, read() records SkippedFile;
                  Collected; tcp_key/path_key), envfiles.py, node.py (package.json),
                  vite.py, python.py (poe/taskipy/pdm/hatch/rye), compose.py (compose-go file
                  choice + project-name precedence; SafeLoader only, pure Python), runtime.py
                  (ProcessTable protocol, PsutilTable; cwd inside a worktree = attribution; never
                  cmdline/environ), layout.py (which
                  directories: 3 deep, never into another .git, skip list), static.py
  git/            porcelain.py (parse `worktree list --porcelain -z`), discovery.py (git_argv: -c
                  core.fsmonitor=false -C DIR; GIT_ENV: optional locks off, no prompt, LC_ALL=C)
  rules/          engine.py (Rule, Context, evaluate, status_for: deny fails probable/confirmed only),
                  catalog.py (order), shared.py (collision rules), runtime.py (PORT-002,
                  RUNTIME-001), context.py (DB-002, CONFIG-001, ENV-001, GIT-002, POLICY-001);
                  docs/rules.md lists every rule (a test compares it with the catalog);
                  rules.md is a copy shipped for explain: edit docs/rules.md, copy it over
  reports/        terminal.py (plain Text; display_path() escapes control characters;
                  worktree_names()), findings.py (scan report; caused_by shown under the cause)
                  json_report.py (+ summary; docs/json-schema-v1.json: change both or neither),
                  markdown.py (escaped; cell_code), sarif.py (2.1.0; located problems only)
tests/
  conftest.py     autouse no_network guard (UNIX sockets allowed); HYPOTHESIS_PROFILE=thorough
  fakes.py        FakeRunner: scripted commands only, anything else fails the test;
                  FakeProcessTable for the runtime observation
  gitrepos.py     real repositories in tmp dirs (make_repo, add_worktree; global git config off),
                  tree_digest() to prove a scan wrote nothing, same_path() for Windows paths
  fixtures/git/   real porcelain captures (binary in .gitattributes: NULs and a newline in a path)
  fixtures/policy/ hand-written policy files
  fixtures/env/   hand-written .env files (no real credentials); vite/, python/, compose/: configs
  unit/           unit tests; Git fixtures are real temporary repositories
  contract/       JSON schema contract (every model field in the schema) and the canary test:
                  planted secrets must reach no renderer
docs/roadmap.md   requirement IDs WTS-001 … and what v0.1 includes
docs/policy.md    every key of .worktree-shield.toml, levels, precedence, what makes a file invalid
docs/what-is-read.md  every file and directory the collectors read, and what they keep
docs/cli.md       every command, option and exit code
docs/rules.md     every WTS rule, how status follows from policy level and certainty
docs/json-output.md   JSON summary fields, SARIF mapping, Markdown; json-schema-v1.json
examples/         conflicting-worktrees/build.py: three colliding worktrees (--fixed: none)
scripts/          check_sarif.py (CI validates SARIF against the pinned OASIS schema)
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
- Runtime: a listener belongs to a worktree only through its process's working directory, never its
  name; read nothing else from a process (no `cmdline`, no `environ`).
- `.env` and `.env.local` only with explicit opt-in; `.env.example`/`.env.template` are fine.
- Subprocesses: argument lists only (no `shell=True`), always a timeout and an output cap, always through the
  command runner.
- Listen ports and client endpoints are different resource kinds; shared Postgres at 5432 is not a bind collision.
- Static evidence gives *probable* at most; *confirmed* needs a running process attributed by its working
  directory. When in doubt, `unknown`.
- Test files with non-ASCII content are written with `encoding="utf-8"`: Windows CI defaults to cp1252.
- Tests first where possible: `@pytest.mark.xfail(strict=True, reason="WTS-0xx")`, then implement and drop the
  marker.

## Commits

One logical change per commit; imperative subject of at most 72 characters; a body that explains why; a
`Refs: WTS-0xx` trailer when a requirement applies. Every commit passes the CI command above.
