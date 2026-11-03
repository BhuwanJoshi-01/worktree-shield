## What does this change?

<!-- What and why, from the user's point of view. Link the issue if there is one. -->

Requirement IDs: <!-- e.g. WTS-005, or "none" -->

## How was it tested?

<!-- Unit tests and fixtures added; real repositories tried, if any. -->

Tried on a real multi-worktree repository: <!-- yes (stack) / no -->

## Impact

- Execution and writes: <!-- Can this run anything from the scanned repo, or write to it or to .git? -->
- Privacy: <!-- Can any new field carry a credential, an env value or a path with a user name? -->
- False alarms: <!-- Could this report collisions that aren't real? What keeps the certainty honest? -->
- Compatibility: <!-- Changes to CLI flags, exit codes, finding IDs, the JSON schema or SARIF? -->

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q` passes
- [ ] Nothing from the scanned repository is executed; nothing is written to it
- [ ] Negative cases are tested (malformed config, missing worktree, permission denied, secrets in input)
- [ ] CHANGELOG.md and docs updated if behaviour, flags or output changed
