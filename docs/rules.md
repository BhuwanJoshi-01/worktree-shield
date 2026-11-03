# Rules

Every finding has a stable ID. CI pipelines and agents can rely on these IDs, so they never change meaning.

A finding's **status** comes from two things: the policy level for its kind of sharing (see
[policy.md](policy.md)) and the **certainty** of the collision:

| Level | Confirmed or probable | Possible |
| --- | --- | --- |
| `deny` | fail | warn |
| `warn` | warn | warn |
| `allow` | pass, with the reason | pass |

`--strict` exits with 1 when a finding fails. A *possible* collision never fails a run. Certainty is:

- **confirmed**: a running server, tied to a worktree by its working directory, holds the resource;
- **probable**: the configuration of two worktrees certainly names the same resource;
- **possible**: it depends on how a host name resolves, how a path is used, or Vite moving to the next free port.

A rule with nothing to look at is *not applicable*. Runtime rules are *not tested* when running processes were
not looked at (`--scope static`).

Outside a Git repository, `scan` exits with code 3 instead of reporting a finding.

## WTS-PORT-001: A listen port configured in more than one worktree

Two or more worktrees start a server on the same port and overlapping addresses: `*`, `0.0.0.0` and `::` take
every address. Only one server can listen at a time. Policy: `shared_host_ports` (default `deny`).

*Fix:* give each worktree its own port in its `.env`, or run one server at a time.

## WTS-PORT-002: A configured port already held by a running process

A port a worktree configures is in use right now. Either a server running in another worktree holds it
(confirmed), or a process outside the worktrees does, in which case the owner is shown if it is visible.
Policy: `shared_host_ports`.

*Fix:* stop the leftover server, or use another port.

## WTS-DB-001: A database used by more than one worktree

Two or more worktrees connect to the same database: the same engine, server, port and name. `localhost`,
`127.0.0.1` and `::1` count as one server. Migrations, seed data and tests of one worktree change the data of
the other. Policy: `shared_database` (default `warn`). A server whose port is listed in `[allow] ports` counts as
shared infrastructure, and its findings pass.

*Fix:* give each worktree its own database name.

## WTS-DB-002: A database URL that could not be identified safely

A variable holds a database URL whose server cannot be found with certainty. Examples: an unencoded `/`, `?` or
`#` in the password, a list of hosts, or `${DB_HOST}`. The value is never shown. Status: unknown.

*Fix:* percent-encode the password and spell out the host.

## WTS-DOCKER-001: A Compose project name shared by worktrees

The project name prefixes containers, networks and named volumes, so `docker compose up` in one worktree takes
over the other's stack. A `name:` in the compose file, or a compose file in a subdirectory such as `infra/`,
gives every worktree the same name. Policy: `shared_compose_projects` (default `warn`).

*Fix:* set `COMPOSE_PROJECT_NAME` per worktree, or drop `name:`.

## WTS-DOCKER-002: A fixed container name set in more than one worktree

A Docker daemon runs one container of a given name, so starting the second stack replaces the first or fails.
Policy: `fixed_container_names` (default `warn`).

*Fix:* remove `container_name`, or build it from `${COMPOSE_PROJECT_NAME}`.

## WTS-DOCKER-003: A Docker volume mounted in more than one worktree

The worktrees read and write the same data. When the volume is shared only because the project name is, the
finding follows from WTS-DOCKER-001. Policy: `shared_compose_projects`.

*Fix:* let Compose prefix the volume with the project name, or mark it external on purpose.

## WTS-PATH-001: An absolute path more than one worktree writes to

The same absolute directory, or one inside the other, is configured in two or more worktrees. Policy:
`shared_absolute_paths` (default `warn`). Paths at or below an entry of `[allow] paths` pass.

*Fix:* use a directory per worktree, or allow the path.

## WTS-ENV-001: .env files the scan did not read

`.env` and `.env.local` are read only with `--include-env`. A `.env` that was left out can set other ports or
databases than the templates, so a finding may be wrong or missing. Status: unknown.

*Fix:* scan with `--include-env`. Only ports, database servers and paths are kept.

## WTS-CONFIG-001: Configuration that could not be read

A file was refused (too large, invalid, a link out of the worktree), or a value could not be identified (for
example a port that depends on a variable no file sets). Any of these can hide a collision. Status: unknown.

## WTS-GIT-002: A worktree Git lists whose directory is gone

Nothing there can collide, and it was not scanned. worktree-shield never prunes it; `git worktree prune` does.

## WTS-RUNTIME-001: Running processes that could not be tied to a worktree

The runtime view was incomplete. Other users' processes are listed without their owner, and on macOS only the
current user's processes are visible. Collisions with what could not be seen cannot be ruled out. Status:
unknown.

## WTS-POLICY-001: An [allow] entry the configuration contradicts

`[allow] ports` lists a port the worktrees *listen* on. That entry covers servers the worktrees connect to; it
never lets two servers listen on one port, so WTS-PORT-001 still applies.

*Fix:* remove the entry, or give each worktree its own port.
