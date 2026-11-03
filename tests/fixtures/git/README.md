# Git fixtures

`git worktree list --porcelain -z` output, **real** captures from git 2.53.0 on Linux (2026-11-03), with the
temporary directory renamed `/home/user/src`:

| File | Repository |
| --- | --- |
| `worktree-list-odd.porcelain` | a main worktree and linked worktrees named `with space`, `ünïcode` and `new<newline>line`, a detached worktree locked with the reason "on a USB disk", and one whose directory was deleted (prunable) |
| `worktree-list-bare.porcelain` | a bare repository with one linked worktree |

Most tests build real temporary repositories instead; these files pin the format.
