# What worktree-shield reads

Everything below is read as **data**: files are parsed, never imported, evaluated or run, and nothing is written.
Every file goes through one reader that stays inside the worktree (a link out of it is refused), opens regular
files only and refuses a file larger than `scan.max_file_bytes` (256 KiB by default) instead of reading part of
it. Refused files are listed under *Not read* in the output, because an unread file can hide a collision.

## Which directories

The root of each worktree and its subdirectories up to three levels down (`apps/web`, `services/api/v2`), but
only those holding one of the files below. The walk lists directories without opening files and:

- never follows a link to a directory;
- does not enter a directory with its own `.git` entry: that is another worktree or a submodule, scanned as
  itself if it is a worktree of this repository;
- skips hidden directories and `node_modules`, `bower_components`, `vendor`, `third_party`, `site-packages`,
  `venv`, `dist`, `build`, `out`, `target`, `coverage`, `__pycache__`, `fixtures`, `__fixtures__`, `testdata`
  and `examples`;
- stops after 2000 directories and says so.

Bare and prunable worktrees have no files and are left out.

## Which files, and what is kept

| File | What is kept |
| --- | --- |
| `.env.example`, `.env.sample`, `.env.template` | Always read. See below. |
| `.env`, `.env.local` | Only with `--include-env` or `include_env_files = true` in the policy. See below. |
| `package.json` | Listen ports in `scripts` and npm's `config.port`. |
| `vite.config.{js,ts,mjs,mts,cjs,cts}` | `server.port`, `preview.port` (with `host` and `strictPort`), absolute `cacheDir` and `build.outDir`, when they are literal values. |
| `pyproject.toml` | Listen ports in the tasks of poe, taskipy, pdm, hatch and rye, including a task's `env`. |
| `compose.yaml` and the other Compose file names, plus the override file | Project name, `container_name`, published host ports, absolute bind mounts and named volumes. See below. |
| `Procfile`, `Procfile.dev` | Listen ports in each process command (foreman, honcho, Heroku, Rails `bin/dev`). |
| `.devcontainer/devcontainer.json`, `.devcontainer.json` | `appPort` (published on the host) and `forwardPorts` (forwarded to localhost; the editor moves them to another port when taken, so they never fail `--strict` alone). Comments and trailing commas are allowed. |

When `.env` files are read, a variable set in `.env` or `.env.local` replaces the templates' value for that variable
in the same folder, and `.env.local` replaces `.env`, as dotenv tools load them; the templates' other variables still
count. Without `--include-env` the templates stand for what the app will run with.

From `.env` files a value is kept only as one of these, and every other value is dropped right after parsing:

- **Listen ports:** `PORT` and `*_PORT` holding a number. A literal `HOST`/`*_HOST` with the same prefix narrows
  the address.
- **Client endpoints:** a `*_PORT` whose name mentions a server the app connects to (`DB`, `POSTGRES`, `PG`,
  `REDIS`, `MONGO`, `MYSQL`, `KAFKA`, `SMTP` and similar). These never collide, since many clients can share one
  server.
- **Databases:** any value that is a Postgres, MySQL/MariaDB, Redis, MongoDB or SQLite URL, reduced to engine,
  host, port and database. User names and passwords are dropped while parsing. A URL whose host cannot be found
  safely (an unencoded `/`, `?` or `#` in the password, a host list, `${DB_HOST}`) is listed under *Could not be
  identified* by its variable name only. In-memory and relative SQLite files are not shared and are not listed.
- **Absolute paths:** in variables whose name has a word saying they are written to, such as `DIR`, `PATH`,
  `CACHE`, `LOG`, `UPLOAD`, `DATA`, `OUTPUT` or `TMP` (`UPLOAD_DIR`, `CACHE_PATH`). Search paths (`PATH`,
  `PYTHONPATH`), installations (`JAVA_HOME`), certificates (`SSL_CERT_FILE`) and configuration directories
  (`CONFIG_DIR`) are read-only by nature and are not listed.

`${VAR}` and `$VAR` are never expanded. A value that refers to another variable is skipped, and the variable is
found where it is defined.

## Ports in commands

Scripts and tasks are split like a shell would split them, without running or expanding anything. The
recognised spellings are:

- `--port 5173`, `--port=5173`, `-p 3001`, `-l 5000`, `--listen 5000`;
- `--bind 127.0.0.1:8000`, `-b :8000`, `-S localhost:8000`;
- `PORT=4000 node server.js`;
- the argument of `runserver` and `http.server`;
- quoted commands passed to tools such as `concurrently`;
- `--host` beside one of the above.

Parts of a command that run a client (`psql`, `redis-cli`, `ssh`, `curl`, `docker` …) are ignored, so their `-p`
never counts. Only the fragment that names the port is kept, never the whole command, which may hold other
values.

## Docker Compose

Files are chosen the way Compose chooses them:

- the first of `compose.yaml`, `compose.yml`, `docker-compose.yml` and `docker-compose.yaml` in a directory;
- plus the first of `compose.override.yml`, `compose.override.yaml`, `docker-compose.override.yml` and
  `docker-compose.override.yaml` next to it.

They are parsed with PyYAML's safe loader, which builds plain data only: Python tags are refused. Docker is
never contacted, so the result is the same whether the daemon is running or not.

- **Project name:** containers, networks and named volumes are all prefixed with it, so two worktrees with the
  same project name share all of them. Compose's precedence is followed: `COMPOSE_PROJECT_NAME` from `.env`
  (when env files are read), then the last non-empty `name:`, then the directory name. The name is
  normalised as Compose does it: lower case, only `a-z 0-9 _ -`. A `name:` in the file, or a compose file in a
  subdirectory such as `infra/`, gives every worktree the same project name. `COMPOSE_PROJECT_NAME` set in the
  shell, or in a `.env` that was not read, overrides what is shown.
- **`container_name`:** a fixed name is global on a Docker daemon.
- **Ports:** host ports published in the short or long syntax, with ranges and protocols. A container port alone
  gets a free host port from Docker and is not listed.
- **Bind mounts:** absolute and `~` host paths that are not read-only. Relative paths belong to each worktree.
- **Named volumes:** `<project>_<name>`, or the volume's own `name:`, or its key when `external: true`.

Values written with `${VAR}` are filled in from the `.env` next to the compose file when env files are read.
Otherwise defaults (`${WEB_PORT:-8080}`) are used, assuming the variable is not set in the shell. A value that
needs a variable no file sets, or that is not valid Compose, is listed under *Could not be identified*. In
override files, a service's last `container_name` counts; ports and volumes of all files are listed together.
A compose file that cannot be parsed yields nothing and is listed under *Not read*.

## Running processes

Unless `--no-runtime` is given or the policy sets `include_runtime = false`, the scan also looks at the listening
TCP and bound UDP sockets the system shows. For each process that owns one, it reads the process **name and
working directory** and nothing else: no command line, no environment, nothing is signalled, and no root or
administrator rights are needed.

A listener counts for a worktree only when its working directory lies inside that worktree (the innermost one,
for nested worktrees). A process called `node` or `python` says nothing about which worktree started it, so the
name is never used. A listener that cannot be tied to a worktree is listed only when its port is one a worktree
configures, with the reason:

- the owner is a process of another user (Linux lists such sockets without their owner);
- the process ended while it was looked at;
- it cannot be inspected without more privileges;
- its working directory cannot be read;
- it runs outside every worktree.

On macOS, listing every socket needs root, so only the current user's processes are seen; the output says
so. The view is a snapshot of one moment: a server started a second later is not in it.

## What is not read

Not read in this version:

- implicit defaults (Vite's 5173 when no port is set; it moves to the next free port anyway);
- ports computed in code (`Number(process.env.PORT)`);
- other dev-server configuration;
- `COMPOSE_FILE`, `-f` and `-p` options given on the command line;
- Compose `profiles`, `network_mode: host` and network names.
