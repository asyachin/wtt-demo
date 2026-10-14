# Application Inventory

This document describes the application exactly as it is today, before any of the work in the deployment plan. It is the baseline. Every defect listed here has a block that fixes it.

The application is a fork of the Docker `example-voting-app`. It arrived in this repository from an earlier, unrelated project. The code was kept, the earlier project's configuration was not.

## Services

### vote

| Property | Value |
|---|---|
| Language | Python 3.11 |
| Framework | Flask, served by gunicorn in production |
| Entry point | `app/vote/app.py`, WSGI object `app:app` |
| Dependencies | `app/vote/requirements.txt`: `Flask`, `Redis`, `gunicorn`, all without version pins |
| Listening port | 80 |
| Routes | `GET` and `POST` on `/` and on `/vote`, both handled by `hello()` at `app/vote/app.py:29` |
| Environment variables | `OPTION_A` (default `Cats`), `OPTION_B` (default `Dogs`), `REDIS_HOST` (default `redis`), `REDIS_PORT` (default `6379`), `PORT` (development server only) |
| Health endpoint | none |
| Metrics endpoint | none |
| Container user | root |
| Dockerfile | multi-stage, three stages: `base`, `dev`, `final` |

What it does: renders a page with two buttons. On `POST` it pushes one JSON document onto the Redis list `votes` and sets a `voter_id` cookie.

### result

| Property | Value |
|---|---|
| Language | Node.js 18 |
| Framework | Express 4 and Socket.IO 4, with `tini` as process 1 |
| Entry point | `app/result/server.js` |
| Dependencies | `app/result/package.json`, locked by `app/result/package-lock.json` |
| Listening port | 80 (the Dockerfile sets `PORT=80`; the code defaults to 4000) |
| Routes | `GET /` and `GET /result`, both serve `views/index.html`. Static files are mounted at both paths. |
| Socket.IO path | `/result/socket.io`, not the default `/socket.io` |
| Environment variables | `PORT`, `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DATABASE` |
| Health endpoint | none |
| Metrics endpoint | none |
| Container user | root |
| Dockerfile | single stage; `nodemon` is installed globally and ships in the production image |

What it does: every second it runs `SELECT vote, COUNT(id) AS count FROM votes GROUP BY vote` and pushes the result to every connected browser as a `scores` event. The browser page is AngularJS 1.x, vendored as a single minified file.

### worker

| Property | Value |
|---|---|
| Language | C# on .NET 8 |
| Type | console application, no HTTP server |
| Entry point | `app/worker/Program.cs`, `Worker.Program.Main` |
| Dependencies | `Newtonsoft.Json 13.0.1`, `Npgsql 7.0.7`, `StackExchange.Redis 2.6.66`, all pinned |
| Listening port | none |
| Environment variables | `DB_HOST`, `DB_USERNAME`, `DB_PASSWORD`, `DB_NAME`, `REDIS_HOST` |
| Health endpoint | none |
| Metrics endpoint | none |
| Container user | root |
| Dockerfile | multi-stage, build on the SDK image, run on the runtime image |

What it does: polls `LPOP votes` on Redis every 100 ms. For each vote it writes a row into PostgreSQL. When the queue is empty it runs `SELECT 1` to keep the database connection alive.

## Data Services

### Redis

| Property | Value |
|---|---|
| Role | queue only, not a store |
| Key | one list, `votes`, in database 0 |
| Message format | `{"voter_id": "<hex string>", "vote": "a" or "b"}` |
| Producer | `vote`, using `RPUSH` |
| Consumer | `worker`, using `LPOP` |
| Authentication | none, and no service supports a password |
| TLS | not supported by the worker, see defect D4 |
| Persistence | no volume in the current Docker Compose file |

### PostgreSQL

| Property | Value |
|---|---|
| Role | system of record |
| Table | `votes` with columns `id VARCHAR(255) NOT NULL` and `vote VARCHAR(255) NOT NULL` |
| Schema creation | at runtime, by the worker, at `app/worker/Program.cs:112` |
| Primary key | none, see defect D1 |
| Writes | `INSERT INTO votes (id, vote)` at `app/worker/Program.cs:154` |
| Reads | `SELECT vote, COUNT(id) AS count FROM votes GROUP BY vote`, once per second |
| Migrations | none |

## Interfaces the Platform Must Provide

| Service | Needs | Provided by |
|---|---|---|
| `vote` | reachable Redis on `REDIS_HOST:REDIS_PORT` | Kubernetes Service `redis` |
| `result` | reachable PostgreSQL, plus user, password, and database name | Kubernetes Service `postgres` and a Secret |
| `worker` | both of the above | the same |
| all | an HTTP liveness and readiness endpoint | added in Block 02 |
| all | an HTTP `/metrics` endpoint in Prometheus format | added in Block 02 |
| `postgres` | a 10 GiB persistent volume | EBS gp3 through the CSI driver |
| `redis` | a 2 GiB persistent volume | EBS gp3, to avoid losing an in-flight queue on restart |

## Known Defects

These are real problems in the current code. Each one is fixed in a block and each fix is proven by a test. Nothing on this list is cosmetic.

### D1 — Vote counts are wrong

The `votes` table has no primary key and no unique index on `id`. The worker tries `INSERT`, and only falls back to `UPDATE` when the insert raises a database error. Because no constraint exists, the insert never fails, so the `UPDATE` branch at `app/worker/Program.cs:161` is unreachable. A visitor who votes a second time adds a second row, and the totals grow beyond the number of voters.

Fix: add a primary key on `id` through a migration, and change the write to `INSERT ... ON CONFLICT (id) DO UPDATE`. Block 02.

### D2 — Votes are silently dropped after a database reconnect

At `app/worker/Program.cs:55` the vote is removed from Redis. At `app/worker/Program.cs:62` the worker checks whether the database connection is open. If it is not, the worker reconnects and then continues the loop without writing the vote. The vote is already gone from the queue, so it is lost.

Fix: write the vote after reconnecting, in the same iteration. Block 02.

### D3 — Passwords are printed to standard output

`app/worker/Program.cs:29` prints the full PostgreSQL connection string, including the password. `app/result/server.js:45` does the same. Every log collector and every `kubectl logs` call then shows the password.

Fix: remove both lines and log only host, port, and database name. Block 02.

### D4 — The worker cannot be fully configured

The worker does not read `DB_PORT`, so the PostgreSQL port cannot be changed. It does not read `REDIS_PORT` either, because `app/worker/Program.cs:30` uses the hostname alone as the connection string. It also resolves the Redis hostname to an IPv4 address at `app/worker/Program.cs:124` and connects by address, which breaks TLS name validation.

Fix: read `DB_PORT` and `REDIS_PORT`, build complete connection strings, and connect to Redis by hostname. Block 02.

### D5 — The voting page breaks over HTTPS

`app/vote/templates/index.html:30` loads jQuery from `http://code.jquery.com/jquery-latest.min.js` over plain HTTP. On an HTTPS page the browser blocks it. The page still renders, but the jQuery cookie plugin never loads, so the "you voted" state does not work. The page also loads Font Awesome and a jQuery plugin from two other content delivery networks, which makes the page depend on the public internet.

Fix: vendor the three assets into `app/vote/static/` and remove every external reference. Block 02.

### D6 — Dependencies are not pinned

`app/vote/requirements.txt` has no version specifiers at all. Two builds a week apart can produce different images from the same commit, which breaks reproducibility and makes a vulnerability scan meaningless.

Fix: pin every direct dependency to an exact version and commit a lock file. Block 01.

### D7 — Build output is committed

`app/worker/obj/` is in the repository. It contains another developer's absolute paths such as `/Users/diogobarros/diogo_ironhack/example-voting-app/worker/`, their local NuGet cache path, and an unrelated commit hash in `Worker.AssemblyInfo.cs`. The root `.gitignore` is empty, which is why this happened.

Fix: delete the directory and write proper ignore files. Block 00 and Block 01.

### D8 — A stale secret symlink overrides the environment

`app/.env` is a symlink to `/home/vmadmin/.secrets/ironhack-multistack/.env`, which belongs to the previous project. Docker Compose loads `.env` from the project directory automatically, so every local run silently used the wrong credentials and the wrong endpoints.

Fix: delete the symlink and pass the environment file explicitly with `--env-file`. Block 00.

### D9 — The environment file is malformed

`app/.env.dev` and `app/.env.prod` both start with a bare line `eu-north-1` that is not a `KEY=VALUE` pair. `docker compose --env-file` and `source` both fail or warn on it. `app/.env.template` also puts `# Example: ...` comments on the same line as a value, which some Compose versions include in the value.

Fix: rewrite the template with one key per line and no trailing comments, and correct the two environment files in the secret store. Block 00.

### D10 — Everything runs as root

None of the three Dockerfiles sets a user. All three containers run as root, which fails the `restricted` Pod Security Standard and is not acceptable in production.

Fix: add a dedicated non-root user to every image and set `runAsNonRoot` in the Helm chart. Block 01 and Block 12.

### D11 — Dangerous settings inherited from the previous project

`app/docker-compose.deploy.yml` contains plain-text credentials, live AWS RDS and ElastiCache endpoints from the previous project, images from an unrelated Docker Hub account, and `NODE_TLS_REJECT_UNAUTHORIZED: "0"`, which turns off all TLS verification in Node.js.

Fix: delete the file. Nothing in the target architecture uses it. Block 01.

### D12 — Unused dependencies and dead code

`app/result/package.json` declares `stoppable` and `method-override`, and `server.js` never imports either. `server.js` also requires `pg` twice, at lines 3 and 47. The `result` image installs `nodemon` globally and ships it to production.

Fix: remove the unused packages, remove the duplicate import, and move development tooling into a separate build stage. Block 01.

### D13 — The voter identifier loses a character

`app/vote/app.py:32` builds the identifier with `hex(random.getrandbits(64))[2:-1]`. The slice `[2:-1]` comes from Python 2, where `hex()` added a trailing `L`. On Python 3 there is no trailing character, so the slice removes a real hex digit. The identifier still works, but it has 4 fewer bits than intended and the code is misleading.

Fix: use `secrets.token_hex(8)`. Block 02.

## Summary of Changes to the Application

The application stays as it is in structure and in language. See [ADR 0002](../adr/0002-keep-polyglot-application.md). The only code changes are the twelve fixes above, plus the health and metrics endpoints. No feature is added and no service is rewritten.
