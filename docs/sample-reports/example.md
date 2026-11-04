# Worktree collision report

**1 fail, 3 warn, 3 pass, 4 not applicable, 2 not tested** across 3 worktrees. Policy: built-in defaults.

worktree-shield 0.1.0, 2026-11-04T12:00:00Z.

| Status | Rule | Finding | Certainty |
| --- | --- | --- | --- |
| FAIL | `WTS-PORT-001` | Port 5173 is configured in 3 worktrees | probable |
| NOT TESTED | `WTS-PORT-002` | Running processes were not looked at | — |
| WARN | `WTS-DB-001` | The Postgres database app\_dev on localhost:5432 is used by 3 worktrees | probable |
| PASS | `WTS-DB-002` | Every database URL could be identified | — |
| WARN | `WTS-DOCKER-001` | The Compose project app is used by 3 worktrees | probable |
| N/A | `WTS-DOCKER-002` | No Compose service sets a container name | — |
| WARN | `WTS-DOCKER-003` | The Docker volume app\_pgdata is mounted in 3 worktrees | probable |
| N/A | `WTS-PATH-001` | No worktree configures an absolute path | — |
| N/A | `WTS-ENV-001` | No .env files were found | — |
| PASS | `WTS-CONFIG-001` | Every configuration file found was read | — |
| PASS | `WTS-GIT-002` | Every listed worktree exists | — |
| NOT TESTED | `WTS-RUNTIME-001` | Running processes were not looked at | — |
| N/A | `WTS-POLICY-001` | The policy allows nothing explicitly | — |

## What needs attention

### FAIL `WTS-PORT-001`: Port 5173 is configured in 3 worktrees

3 worktrees start a server on port 5173; only one can listen on it at a time.

| Worktree | Where | What |
| --- | --- | --- |
| app | `.env.example:1` | `PORT=5173` |
| app-billing | `.env.example:1` | `PORT=5173` |
| app-login | `.env.example:1` | `PORT=5173` |

**Next step:** Give each worktree its own port, for example in its own .env (PORT=5173 in one, PORT=5174 in the other), or run one server at a time.

**Check afterwards:** `worktree-shield scan --strict --include-env`

*Note:* The servers collide only when both run at the same time on this host.

### WARN `WTS-DB-001`: The Postgres database app\_dev on localhost:5432 is used by 3 worktrees

3 worktrees use the same database; migrations, seed data and tests of one change the data of the other.

| Worktree | Where | What |
| --- | --- | --- |
| app | `.env.example:2` | `DATABASE_URL` |
| app-billing | `.env.example:2` | `DATABASE_URL` |
| app-login | `.env.example:2` | `DATABASE_URL` |

**Next step:** Give each worktree its own database name in its .env (app\_dev\_login, app\_dev\_billing), or allow the server's port in \[allow\] ports if sharing it is intended.

**Check afterwards:** `worktree-shield scan --strict --include-env`

*Note:* Sharing is harmless when the worktrees only read from the database.

### WARN `WTS-DOCKER-001`: The Compose project app is used by 3 worktrees

3 worktrees have the Compose project name app; docker compose up in one takes over the containers, networks and volumes of the other.

| Worktree | Where | What |
| --- | --- | --- |
| app | `compose.yaml:1` | `name: app` |
| app-billing | `compose.yaml:1` | `name: app` |
| app-login | `compose.yaml:1` | `name: app` |

**Next step:** Set COMPOSE\_PROJECT\_NAME in each worktree's .env, or remove name: from the compose file so each worktree's directory name is used.

**Check afterwards:** `worktree-shield scan --strict`

*Note:* The stacks collide only when they run on the same Docker daemon.

### WARN `WTS-DOCKER-003`: The Docker volume app\_pgdata is mounted in 3 worktrees

3 worktrees mount the Docker volume app\_pgdata, so they read and write the same data.

Follows from `WTS-DOCKER-001`.

| Worktree | Where | What |
| --- | --- | --- |
| app | `compose.yaml:6` | `services.db.volumes: pgdata` |
| app-billing | `compose.yaml:6` | `services.db.volumes: pgdata` |
| app-login | `compose.yaml:6` | `services.db.volumes: pgdata` |

**Next step:** Let Compose prefix the volume with the project name (drop its name: or external:), or mark it external on purpose if the data is meant to be shared.

**Check afterwards:** `worktree-shield scan --strict`

*Note:* The data is shared only on the same Docker daemon.

---

Made by [worktree-shield](https://github.com/BhuwanJoshi-01/worktree-shield), read-only: nothing in the repository was run, changed or locked. Redacted from this output: 65 home paths.
