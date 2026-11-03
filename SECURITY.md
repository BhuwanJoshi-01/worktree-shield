# Security Policy

## Supported versions

Only the latest release and the `main` branch receive fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through GitHub instead:
**Security → Report a vulnerability** on this repository
(<https://github.com/BhuwanJoshi-01/worktree-shield/security/advisories/new>).

Include what you found, how to reproduce it, and the impact you expect. You will get an answer within a week,
and a fix or mitigation as soon as possible after that.

## What counts as a security problem here

Worktree Shield reads repositories that may not be yours (a cloned project, a pull request in CI) and its reports
end up in CI logs, SARIF uploads and coding agents. These are in scope:

- **Code execution from the scanned repository.** The tool parses configuration; it never runs project scripts,
  Git hooks, `fsmonitor` programs, `docker compose`, Node, Python or shell code from the repository. A way to make
  a scan execute something is a vulnerability.
- **Secrets in output.** Database passwords, tokens or other values from `.env` files or URLs appearing in
  terminal, JSON, Markdown or SARIF output. Credentials must be discarded as soon as a URL is parsed.
- **Changes to the repository or the system.** A scan must not write to the working trees or `.git` (no index
  locks, no pruning), start or stop containers, kill processes or touch databases.
- **Reading outside the repository** without the user's explicit opt-in, for example by following a symlink.
- **Network access.** Normal use makes no network connections.

Worktree Shield is not a sandbox and does not protect against a malicious process; see the threat model in the
documentation once published.
