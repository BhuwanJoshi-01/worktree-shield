# The policy file: `.worktree-shield.toml`

A repository says which kinds of sharing it accepts in `.worktree-shield.toml` at the top level of a worktree.
The file is optional: without it the built-in defaults below apply, and `worktree-shield` still reports
everything it finds.

`worktree-shield policy` reads and checks the file today; `scan` and `--strict` apply it once they land (see
[the roadmap](roadmap.md)).

```toml
schema_version = 1

[scan]
include_runtime = true          # look at running processes (read-only)
include_env_files = false       # read .env and .env.local too
max_file_bytes = 262144         # larger files are skipped and reported

[policy]                        # allow | warn | deny
shared_host_ports = "deny"
shared_database = "warn"
shared_compose_projects = "warn"
fixed_container_names = "warn"
shared_absolute_paths = "warn"

[allow]
ports = [5432, 6379]            # infrastructure every worktree may connect to
paths = ["/tmp/shared-download-cache"]
```

Check what applies with:

```bash
worktree-shield policy             # this worktree's file, or the defaults
worktree-shield policy --repo PATH
```

Each value the file changes is listed next to the default it replaces.

## Levels

| Level | Meaning |
| --- | --- |
| `allow` | The sharing is intended. It is reported as information and never fails a run. |
| `warn` | It is reported as a warning. `--strict` does not fail on it. |
| `deny` | It is reported as a failure, and `--strict` exits with 1. |

| Key | Kind of sharing | Default |
| --- | --- | --- |
| `shared_host_ports` | Two worktrees listen on the same host port. | `deny`: the second dev server fails to start. |
| `shared_database` | Two worktrees use the same database (host, port and name). | `warn`: a shared dev database is often intended. |
| `shared_compose_projects` | Two worktrees resolve to the same Docker Compose project name. | `warn` |
| `fixed_container_names` | Two worktrees set the same `container_name`. | `warn` |
| `shared_absolute_paths` | Two worktrees write to the same absolute path. | `warn` |

## Allow lists

`allow.ports` lists **endpoints the worktrees connect to as clients**: one Postgres on 5432 that every
worktree uses. It does not allow two processes to *listen* on that port. Listening ports and client endpoints
are different kinds of resource, so allowing shared Postgres never hides two API servers both trying to bind
5432.

`allow.paths` lists absolute paths that the worktrees may share, such as a download cache: POSIX paths
(`/srv/cache`) or Windows paths (`C:\cache`, written `'C:\cache'` or `"C:\\cache"` in TOML).

## Scan settings

| Key | Default | Meaning |
| --- | --- | --- |
| `include_runtime` | `true` | Look at listening sockets and process working directories. Read-only; nothing is signalled. |
| `include_env_files` | `false` | Also read `.env` and `.env.local`. Values are reduced to what a rule needs (a port, a database host and name); secrets never reach a report. `.env.example` and `.env.template` are always read. |
| `max_file_bytes` | `262144` | Files larger than this are skipped and reported, not read in part. 1 to 16777216. |

## Precedence

Command-line flags, then the policy file of the current worktree, then the built-in defaults. There is no
user-wide or system-wide policy. Each worktree reads its own file, which is usually the same committed file;
a bare repository has the defaults.

## What makes a file invalid

The file is TOML read as data: nothing in it is evaluated or run, and there is no key that takes a command.
`worktree-shield` stops with exit code 2 and names the problem when:

- the file is not valid TOML or not UTF-8;
- `schema_version` is missing or is not `1`;
- a section or key is unknown (a misspelt key is an error, not a silent default);
- a value has the wrong type: levels other than `allow`, `warn`, `deny`; ports outside 1–65535; paths that are
  not absolute;
- the file is larger than 64 KiB, is not a regular file, or is a link to a file outside the worktree.
