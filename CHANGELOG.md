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
- `worktree-shield resources [--repo PATH] [--include-env]`: the listen ports,
  databases and absolute paths each worktree declares in `.env.example`/
  `.env.template`/`.env.sample` (and `.env`/`.env.local` with `--include-env`),
  `package.json` scripts, `vite.config.*` and the task runners of
  `pyproject.toml`, with file and line, resources used by several worktrees
  marked. Database URLs are reduced to engine, host, port and database while
  parsing; credentials never reach the output. Files are read as data inside
  the worktree only, with a size cap; nested worktrees and submodules are not
  counted twice. See docs/what-is-read.md.
- Docker Compose in `resources`: project names (with Compose's precedence and
  normalisation), fixed container names, published host ports, absolute bind
  mounts and named volumes from `compose.yaml` and its override file, with
  `${VAR:-default}` interpolation from `.env` when env files are read. Parsed
  with PyYAML's safe loader; Docker is never contacted.
- Running processes in `resources` (`--no-runtime` to skip): listening sockets
  tied to a worktree by the working directory of their process, and listeners
  outside the worktrees on ports a worktree configures. Only process names and
  working directories are read; no root needed.
- `worktree-shield scan [--repo PATH] [--strict] [--scope all|static|runtime]
  [--include-env] [--all]`: thirteen rules with stable IDs (WTS-PORT-001/002,
  WTS-DB-001/002, WTS-DOCKER-001/002/003, WTS-PATH-001, WTS-ENV-001,
  WTS-CONFIG-001, WTS-GIT-002, WTS-RUNTIME-001, WTS-POLICY-001). Collisions are
  confirmed (a running server in another worktree), probable or possible; the
  status follows the policy level, and `--strict` exits 1 when a finding
  fails. A possible collision never fails. See docs/rules.md.
