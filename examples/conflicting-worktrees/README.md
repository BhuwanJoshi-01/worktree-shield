# Three worktrees that collide

`build.py` builds a small repository with three worktrees that all:

- start a dev server on port 5173 (`.env.example`);
- use the Postgres database `app_dev`;
- run the Compose project `app`, whose named volume is then shared too.

```bash
python examples/conflicting-worktrees/build.py /tmp/wts-demo
worktree-shield scan --repo /tmp/wts-demo/app --scope static
```

The scan reports WTS-PORT-001 (fail), WTS-DB-001, WTS-DOCKER-001 and WTS-DOCKER-003, which follows from the
project. With `--strict` it exits 1.

```bash
python examples/conflicting-worktrees/build.py /tmp/wts-fixed --fixed
worktree-shield scan --repo /tmp/wts-fixed/app --scope static --strict   # exits 0
```

In the fixed version each branch commits its own port and database name, and the compose file has no `name:`,
so each worktree's directory name becomes its project name.

The script needs only git and writes nothing outside the directory you give it. `--scope static` keeps the
example independent of whatever else runs on your machine.
