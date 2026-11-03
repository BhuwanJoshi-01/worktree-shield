# Troubleshooting

**"is not inside a Git repository" (exit 3).** Run the command inside a worktree, or point to one with
`--repo PATH`.

**The policy file is rejected (exit 2).** The message names the key at fault. Unknown keys are errors on
purpose, so a typo cannot quietly fall back to a default. `worktree-shield policy` shows what applies once the
file is valid. See [policy.md](policy.md).

**A port I use is not found.** Only literal values are read:

- a port computed in code (`Number(process.env.PORT)`) is not read, but the variable is, where it is defined;
- implicit defaults are not read: Vite takes 5173 when nothing is set, and moves on by itself;
- `.env` is read only with `--include-env`.

`worktree-shield resources` shows everything that was found, and *Not read* lists what was skipped.

**A collision is reported that cannot happen.**

- If the sharing is intended, for example one Postgres for every worktree, allow it: put `ports = [5432]` under
  `[allow]` in `.worktree-shield.toml`. For a shared directory, add it to `[allow] paths`.
- If the worktrees never run at the same time, lower the level, for example `shared_host_ports = "warn"`.
- If Vite moves to the next free port, the finding is already *possible*, and it never fails `--strict`.

**WTS-PORT-002 names a process I do not recognise.** The port is in use right now. If the process belongs to
another user, it is shown without a name. `ss -ltnp` (Linux) or `lsof -iTCP -sTCP:LISTEN` (macOS) shows who
holds a port.

**WTS-RUNTIME-001 says the view is incomplete.** Linux lists other users' sockets without their owner. On macOS,
only your own processes are visible without root. worktree-shield never asks for more rights; the static findings
still apply.

**A worktree inside another one is counted twice.** It is not: the walk never enters a directory with its own
`.git` entry. If you see this, please open an issue with `worktree-shield resources` attached.

**Paths look different on Windows.** Worktree names use `\` and paths in your home show as `~\…`. Both are expected.
