# Command reference

`worktree-shield` and its alias `wtshield` take the same commands. Every command reads only: nothing in the
repository or in `.git` is run, changed or locked, no process is signalled, Docker is never contacted, and
secrets are never printed. `report --output FILE` writes that one file and nothing else.

Every command that looks at a repository takes `--repo PATH`, a directory inside it (the default is the current
directory).

## scan

```bash
worktree-shield scan [--strict] [--scope all|static|runtime] [--include-env] [--format FORMAT] [--all]
```

Finds the ports, databases, Compose names and paths that the worktrees share, and reports each as a finding with
a stable ID (see [rules.md](rules.md)).

| Option | Effect |
| --- | --- |
| `--strict` | Exit 1 when a finding fails under the policy. A *possible* collision never fails. |
| `--scope static` | Configuration only; running processes are left alone. Use it in CI and on shared machines. |
| `--scope runtime` | Only what running processes show (WTS-PORT-002, WTS-RUNTIME-001). |
| `--include-env` | Also read `.env` and `.env.local`. Only ports, database servers and paths are kept. |
| `--format` | `terminal` (default), or `json`, `markdown` or `sarif` on stdout. |
| `--all` | Also list the checks that passed or did not apply. |

## report

```bash
worktree-shield report [-f markdown|json|sarif] [-o FILE] [--force] [--strict] [--scope …] [--include-env]
```

Writes the scan as a report: Markdown for an issue or a pull request, JSON for scripts, SARIF for code
scanning. Without `-o`, or with `-o -`, it goes to stdout. An existing file is overwritten only with `--force`.
See [json-output.md](json-output.md).

## plan

```bash
worktree-shield plan [--scope …] [--include-env]
```

Suggests one change per worktree and claim that would resolve each collision, and applies none of them. The
current worktree keeps its values. Every other worktree gets:

- a free port;
- a database name of its own;
- its directory name as the Compose project name;
- a path of its own.

Values read from a committed `.env` template are overridden in that worktree's `.env`.

## resources

```bash
worktree-shield resources [--include-env] [--no-runtime]
```

Lists every resource each worktree declares or holds, with file and line, and marks the ones that more than one
worktree uses. It also lists what could not be read. See [what-is-read.md](what-is-read.md).

## policy

```bash
worktree-shield policy
```

Shows the effective policy, which is `.worktree-shield.toml` in the current worktree or the defaults. Each value
the file changes is listed next to the default it replaces. A file that cannot be used exits with 2. See
[policy.md](policy.md).

## worktrees

```bash
worktree-shield worktrees
```

Lists the worktrees as Git records them, including locked, detached, bare and prunable ones.

## explain and rules

```bash
worktree-shield rules
worktree-shield explain WTS-PORT-001
```

`rules` lists every rule ID with its title. `explain` prints a rule's documentation: what it finds, which policy
key decides its status, and how to fix it.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The command ran. Findings do not change the exit code unless `--strict` is given. |
| 1 | `--strict`: a finding failed under the policy. |
| 2 | A usage error, an unusable policy file, an existing `--output` file without `--force`, or an internal error. |
| 3 | The directory is not inside a Git repository. |
| 130 | Interrupted (Ctrl+C). |

`WTS_DEBUG=1` prints the traceback of an internal error instead of one redacted line.
