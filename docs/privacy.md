# Privacy

worktree-shield runs on your machine, sends nothing anywhere and has no telemetry. This page lists what it reads,
what it keeps, and what can appear in a report.

## Read

- **Git:** `git rev-parse` and `git worktree list`. These read `.git` without taking locks.
- **Configuration:** the files listed in [what-is-read.md](what-is-read.md), each through a reader that refuses
  links out of the worktree and files over the size cap.
- **`.env` and `.env.local`:** only with `--include-env` or `include_env_files = true`. Without it, a scan notes that
  they exist but never opens them.
- **Running processes:** listening sockets and, for each owner, the process name and working directory. A process's
  command line and environment are never read, because both can hold secrets.

## Kept

From configuration, only these are kept:

- port numbers;
- database identities: engine, host, port and database name;
- Compose project, container and volume names;
- absolute paths in variables that name a writable location.

The value of every other variable is dropped as soon as the line is parsed. A database URL loses its user name and
password while it is parsed, so they reach neither the snapshot nor an error message. A URL that cannot be read
safely is reported by its variable name only.

## Shown

Every output is passed through a redactor before it is printed or written: the terminal reports, JSON, Markdown,
SARIF and the plan. The redactor replaces:

- your home directory with `~`, and other users' homes with `/home/<user>`;
- your user and host names with `<user>` and `<host>` when they appear as whole words;
- values assigned to names that look secret (`*_PASSWORD`, `*_TOKEN`, `API_KEY` …) with `<redacted>`;
- credentials inside URLs, and known token formats (GitHub, Hugging Face, OpenAI, Anthropic, AWS, Slack, JWT).

Each report ends with what was redacted, for example *Redacted from this output: 3 home paths*. A test plants
passwords, API keys and credentialed URLs in `.env` files and checks that none of them reaches any output format.

Read a report before you share it: paths and branch names are still in it, and they can say something about your
work.
