# Contributing

Thanks for helping! By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). The most useful
contributions right now:

- **Real collision stories.** Two worktrees (or agents) that fought over a port, a database, a Compose project or
  a folder. Open a *Test report* issue describing the setup, even if Worktree Shield already caught it.
- **Fixtures** for config formats and edge cases the tests don't cover yet. Never include real credentials; use
  obviously fake ones like `postgres://user:CHANGEME@localhost/app_dev`.
- **Bug reports, especially false positives**, and pull requests.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and Git. Docker is **not** needed; Compose files are parsed, never run.

```bash
git clone https://github.com/BhuwanJoshi-01/worktree-shield.git
cd worktree-shield
uv sync
```

Before every commit, run the same checks as CI:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

## How the code is organised

1. **CLI** parses arguments and wires the other layers together. No inference lives here.
2. **Git discovery** lists the worktrees of one repository through `git worktree list --porcelain -z`.
3. **Collectors** read an allowlist of config files in each worktree (and, optionally, listening processes) and
   turn them into typed *resource claims* with the file and line they came from.
4. **Normalisation and the collision graph** decide which claims point at the same resource, keeping *possible*
   and *confirmed* overlaps apart.
5. **Policy rules** are pure functions from the graph and the repository's policy to findings.
6. **Renderers** produce terminal, JSON, Markdown or SARIF output, after redaction.

## Rules for changes

- **Never execute anything from the scanned repository**: no package scripts, Git hooks, `vite.config.*`, Compose,
  Python or shell. Config is parsed as data, with size limits.
- **Read-only.** No writes to the worktrees or `.git`; Git runs with `GIT_OPTIONAL_LOCKS=0` and
  `-c core.fsmonitor=false`. No `prune`, `kill`, `docker`, `createdb` or `.env` rewriting.
- **Credentials are dropped on parse.** A database URL is reduced to scheme, host, port and database name the moment
  it is read; the password never reaches a model, a log or a report.
- **Subprocesses** take an argument list (never `shell=True`), a timeout and an output limit, and go through the
  command runner so tests can replace them.
- **Be conservative.** Two worktrees declaring port 5173 is a *probable* collision, not a confirmed one. A process
  only belongs to a worktree when its working directory proves it. Prefer `unknown` over a false alarm.
- **Listening is not connecting.** Two services binding port 5432 collide; two apps connecting to one Postgres on
  5432 usually don't. Keep the two resource kinds apart.
- **Tests first** where you can: add the tests marked `@pytest.mark.xfail(strict=True, reason="WTS-0xx")`, then
  implement the behaviour and remove the marker. Build Git fixtures as real temporary repositories.

## Commits and pull requests

- One logical change per commit, with an imperative subject (at most 72 characters) and a body that explains why.
- Mention the requirement ID when there is one, as a `Refs: WTS-005` trailer.
