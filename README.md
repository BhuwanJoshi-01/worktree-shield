# Worktree Shield

**Audit parallel Git worktrees for shared ports, databases and Docker resources before your agents collide.**

> **Status: in development.** Nothing is released yet. The commands below are the planned interface for 0.1.0;
> see the [roadmap](docs/roadmap.md).

Git worktrees give every agent or task its own checkout, but not its own infrastructure. Three worktrees can still
start a dev server on the same port, migrate the same `app_dev` database, reuse one Docker Compose project name or
write to the same absolute folder:

```text
repo-main/              API -> :8000     DB -> postgres://localhost/app_dev
repo-feature-login/     API -> :8000     DB -> postgres://localhost/app_dev
repo-feature-billing/   API -> :8001     DB -> postgres://localhost/app_dev
```

Worktree Shield finds these shared resources in worktrees that **already exist**, however they were created
(plain `git worktree`, a worktree manager or a coding agent), and reports each one with the file and line it came
from and how certain the collision is:

```bash
worktree-shield scan                 # all worktrees of the current repository, read-only
worktree-shield scan --strict        # non-zero exit when the policy fails, for CI and agent preflight
worktree-shield plan                 # suggested changes, printed only, never applied
worktree-shield report --format sarif --output conflicts.sarif
```

## What it promises

- **Read-only.** It never writes to your worktrees or `.git`, never prunes, kills, starts containers or touches
  databases.
- **Nothing from the repository runs.** Config files are parsed as data; package scripts, Git hooks, Vite configs
  and Compose are never executed. Docker doesn't need to be running.
- **No secrets in output.** Database URLs are reduced to host, port and database name as soon as they are read.
  `.env` files are only read when you opt in.
- **Honest certainty.** Two worktrees declaring the same port is a *probable* collision; it is *confirmed* only when
  a running process proves it. Intentionally shared infrastructure (one Postgres for everyone) can be allowed by
  policy.
- No network access, no telemetry.

## Alternatives

Worktree managers can avoid collisions when they create the worktrees:
[workz](https://github.com/rohansx/workz) allocates ports, database names and Compose project names, and
[worktree-compose](https://github.com/mostafasudo/worktree-compose) checks port collisions between the worktrees it
manages with `wtc doctor`. Worktree Shield doesn't create anything; it audits whatever is already there, with a
policy file, CI exit codes and SARIF.

## License

[MIT](LICENSE)
