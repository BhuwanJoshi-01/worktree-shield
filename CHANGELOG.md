# Changelog

All notable changes to this project are listed here. Versions follow
[Semantic Versioning](https://semver.org/). The JSON report format has its own
`schema_version`, and finding IDs (`WTS-PORT-001` …) are stable: CI pipelines
and agents depend on both.

## Unreleased

Nothing released yet. The first release (0.1.0) will audit existing worktrees
for shared ports, databases, Docker Compose names and absolute paths.

- `worktree-shield --help` and `--version` (also as `wtshield`). Exit codes: 0
  when the scan ran (whatever it found), 1 for `--strict` failures, 2 for usage
  errors and internal errors, 3 when the directory is not inside a Git
  repository, 130 for Ctrl+C. Internal errors print one redacted line;
  `WTS_DEBUG=1` shows the traceback.
- `worktree-shield worktrees [--repo PATH]`: the worktrees of the repository as
  Git records them (`git worktree list --porcelain -z`), including locked,
  detached, bare and prunable ones, with paths containing spaces, Unicode or
  newlines. git runs with optional locks off, no terminal prompt and no
  fsmonitor, so nothing in `.git` is written. Exits 3 outside a repository.
- `.worktree-shield.toml` policy (schema version 1): levels `allow`/`warn`/`deny`
  for shared host ports, databases, Compose projects, container names and
  absolute paths; scan settings; allow lists for shared client endpoints and
  paths. Read as TOML data with every key checked; unknown keys are errors.
  `worktree-shield policy [--repo PATH]` shows the effective policy and exits 2
  for a file it cannot use. See docs/policy.md.
