# Roadmap

Requirement IDs (`WTS-001` …) are used in issues, pull requests and commit trailers (`Refs: WTS-005`). A
requirement is done when its tests pass and the behaviour was checked on real worktrees, not when the code is
written.

## v0.1: passive audit of existing worktrees

All twelve are implemented and tested on real temporary repositories (see the tests named after each ID). The
release waits for testers on other machines; macOS has not been tried yet.

| ID | Feature | Done when |
| --- | --- | --- |
| WTS-001 | Git worktree discovery | `git worktree list --porcelain -z` is parsed correctly, including locked, detached, prunable worktrees and odd file names |
| WTS-002 | Repository policy | `.worktree-shield.toml` is read with schema validation and defaults; config is data, never code |
| WTS-003 | Port discovery | Explicit port declarations in known config files are found, with the source file and line where possible |
| WTS-004 | Database identity | Allowlisted DB URL fields are parsed, credentials discarded, and host + port + database compared |
| WTS-005 | Compose audit | Reused project names, fixed container names and published host ports are found, following Compose's precedence rules |
| WTS-006 | Absolute path audit | The same normalised absolute mutable path used by several worktrees is found |
| WTS-007 | Runtime observation | Listening processes are tied to a worktree only on strong evidence (their working directory) |
| WTS-008 | Collision categories | Each collision is confirmed, probable, possible or unknown, with a severity and a reason |
| WTS-009 | Reports | Terminal, JSON and Markdown with stable finding IDs and redaction |
| WTS-010 | Safe CI behaviour | `--strict` exit semantics, no repository changes, no secret values in any output |
| WTS-011 | Works without config | A sample repository gives useful findings without writing a policy file |
| WTS-012 | Fixtures | Real temporary Git repositories with several worktrees and Compose, DB and port scenarios are tested |

Also in v0.1, for CI: SARIF 2.1.0 output (validated against the schema, paths and secrets sanitised) and a
GitHub Action that runs the static scan. Runtime scans in CI are reported as not meaningful there.

## v0.2

A documented preflight contract for coding agents: `worktree-shield scan --strict --format json` before starting
a second dev server or migrating a database.

## v0.3

Optional readers for the configuration of worktree managers (`.wtcrc` from worktree-compose, the workz registry),
so worktrees they created can be audited with their intended allocations.

## Later

Integrations with environment managers and devcontainers by exporting policy results, not by provisioning.

## Not planned

Creating, pruning or cleaning worktrees; starting or stopping containers; killing processes; creating or dropping
databases; rewriting `.env` files; acting as a sandbox or secret scanner.
