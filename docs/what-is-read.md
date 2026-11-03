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

## What is not read

Not read in this version:

- implicit defaults (Vite's 5173 when no port is set; it moves to the next free port anyway);
- ports computed in code (`Number(process.env.PORT)`);
- other dev-server configuration;
- Docker Compose files. Compose support is planned; see [the roadmap](roadmap.md).
