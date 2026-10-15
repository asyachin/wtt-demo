# Application workloads and defect register

The workload is a fork of Docker's `example-voting-app`, carried into this repository from an earlier unrelated project. The code was kept; the earlier project's configuration was discarded in Block 00.

The application is not the deliverable. It exists to give the platform something real to carry. Defects are fixed when they affect the demonstration or leak credentials, and otherwise recorded here rather than silently tolerated.

## Workloads

Five workloads in namespace `vote-dev`, one replica each.

### vote

| Property | Value |
|---|---|
| Language | Python 3.11, Flask, served by gunicorn with 4 workers |
| Source | `app/vote/` |
| Image | `ghcr.io/asyachin/wtt-demo/vote:9a9bb9e` |
| Port | 80 |
| Routes | `GET` and `POST` on `/` and `/vote` |
| Config | `REDIS_HOST`, `REDIS_PORT` as literal env values |
| Probes | Readiness on `GET /`. **No liveness probe.** |
| Resources | requests 50m CPU / 128Mi; limit 512Mi memory |

Renders two buttons. On `POST` it pushes one JSON document onto the Redis list `votes` and sets a `voter_id` cookie server-side.

The voted-state highlight is rendered by an inline script that only appears in the `POST` response, because `vote` is assigned inside `if request.method == "POST"` (`app/vote/app.py:39-41`). **After a page reload the highlight is gone by design.** Any acceptance test must check the POST response, not a reload.

### result

| Property | Value |
|---|---|
| Language | Node.js 22, Express, Socket.IO, `tini` as PID 1 |
| Source | `app/result/` |
| Image | `ghcr.io/asyachin/wtt-demo/result:f0ea1a0` |
| Port | 80 |
| Socket.IO path | `/result/socket.io` — not the default, and the reason the Gateway route needs a dedicated rule |
| Config | `PORT`, `PG_HOST`, `PG_PORT` literal; `PG_USER`, `PG_PASSWORD`, `PG_DATABASE` from `secretKeyRef` |
| Probes | Readiness on `GET /`. **No liveness probe.** |
| Frontend | AngularJS 1.x, vendored unversioned in `views/` |

Polls `SELECT vote, COUNT(id) FROM votes GROUP BY vote` once per second and pushes a `scores` event to connected browsers.

### worker

| Property | Value |
|---|---|
| Language | C# on .NET 8, console application, no HTTP server |
| Source | `app/worker/` |
| Image | `ghcr.io/asyachin/wtt-demo/worker:f75d7b7` |
| Config | `REDIS_HOST`, `DB_HOST` literal; `DB_USERNAME`, `DB_PASSWORD`, `DB_NAME` from `secretKeyRef` |
| Probes | **None.** No HTTP endpoint to probe. |

Polls `LPOP votes` every 100 ms and inserts each vote into PostgreSQL. Creates the `votes` table at startup if it does not exist.

### postgres

| Property | Value |
|---|---|
| Image | `postgres:17.11-alpine` |
| Kind | StatefulSet, 1 replica, headless Service |
| Storage | 5 GiB `gp3` PVC, encrypted, reclaim policy `Delete` |
| Config | All of `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` via `envFrom: secretRef` |
| Probes | `pg_isready` for readiness and liveness |

Table `votes (id VARCHAR(255) NOT NULL, vote VARCHAR(255) NOT NULL)`. No primary key — see defect D1.

### redis

| Property | Value |
|---|---|
| Image | `redis:7.4.11-alpine` |
| Kind | Deployment, 1 replica |
| Persistence | **None.** `--appendonly no --save ""`, no volume. |
| Probes | `redis-cli ping` for readiness and liveness |

A queue, not a store. Deliberately ephemeral. A restart loses votes not yet consumed by the worker.

## Data flow

```
vote (Flask)
  │  RPUSH votes  {"voter_id": "...", "vote": "a" | "b"}
  ▼
redis  list "votes"                       ephemeral
  │  LPOP votes, every 100 ms
  ▼
worker (.NET)
  │  INSERT INTO votes (id, vote)
  ▼
postgres                                  system of record, 5 GiB EBS
  │  SELECT ... GROUP BY vote, every 1 s
  ▼
result (Node.js)
  │  Socket.IO "scores" on /result/socket.io
  ▼
Browser
```

## Images

Built and pushed manually. There is no CI pipeline; Block 07 owns that.

| Image | Tag | Built from |
|---|---|---|
| `ghcr.io/asyachin/wtt-demo/vote` | `9a9bb9e` | `fix(vote): load pinned jQuery over HTTPS` |
| `ghcr.io/asyachin/wtt-demo/result` | `f0ea1a0` | `build: upgrade Result runtime to Node.js 22` |
| `ghcr.io/asyachin/wtt-demo/worker` | `f75d7b7` | `fix(worker): prevent PostgreSQL credentials in logs` |

The tag is the short SHA of the commit whose source produced it, which makes any running image traceable to a commit. The three services are at different generations, which is expected: each was rebuilt only when its own source changed.

`imagePullPolicy: Always` is set on all three. Because the tags are immutable in practice, this costs a registry round trip on every pod start without providing a benefit. Harmless, worth tidying.

No image is signed, no SBOM is produced, and no vulnerability scan runs. All three depend on CI existing first.

## Secrets

One application secret exists.

| Property | Value |
|---|---|
| Name | `postgres-credentials`, namespace `vote-dev` |
| Keys | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| Created | **MANUAL.** Outside Git, by the operator. |
| In Git | No. No manifest references its values, only `secretKeyRef` and `envFrom`. |
| Consumers | `postgres` via `envFrom`; `result` and `worker` via individual `secretKeyRef` entries |
| Rotation | `scripts/rotate_k8s_postgres_password.py` |

Because the Secret is a manual object and not present in any manifest, a future Argo CD installation will neither manage nor prune it. That property is relied on in [blocks/05-gitops.md](blocks/05-gitops.md) and is verified there rather than assumed.

A Kubernetes Secret is base64, not encryption. Anyone with `get secret` in `vote-dev` can read the password in clear text. There is no RBAC restriction limiting that today.

Key names present in the Secret have not been read from the cluster from this workstation. Confirm that they match what the manifests consume:

```bash
kubectl -n vote-dev get secret postgres-credentials -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'
```

Rotation helper scripts also exist for the local Docker Compose stack: `scripts/pass.py` and `scripts/pg_pass_rotation.py`.

## Local development

`app/docker-compose.yml` runs the full stack locally with PostgreSQL 17 and Redis 7.4, matching the cluster image versions. It reads `app/.env.dev`, which is not in Git; `app/.env.template` documents the required keys with no values.

```bash
cd app
docker compose --env-file .env.dev up -d --build
docker compose --env-file .env.dev ps
```

Vote on `${VOTE_PORT}`, result on `${RESULT_PORT}`. The local stack gives Redis a volume and enables `--appendonly yes`, which the cluster deliberately does not.

Never rely on an implicit `app/.env`. That file was a symlink into a previous project's secret directory, which Docker Compose loads automatically and which silently overrode the intended values. It was removed in Block 00 and `tests/unit/test_repository_hygiene.py::test_no_env_symlink` keeps it removed.

## Defect register

Status verified by reading the source at commit `a4d979f`. "Demo-visible" means a reviewer could notice it during the demonstration.

### Fixed

| ID | Defect | Fixed in | Evidence |
|---|---|---|---|
| D3 | PostgreSQL connection string, including the password, printed to stdout by both `worker` and `result` | Block 02 | `f75d7b7`; `tests/unit/test_repository_hygiene.py::test_database_connection_string_not_logged` guards the `result` case |
| D5 | Vote page loaded jQuery over plain `http://`, which browsers block as mixed active content on an HTTPS page | Block 04, partial | `9a9bb9e` changed the reference to `https://code.jquery.com/jquery-3.7.1.min.js`; `a4d979f` deployed image `vote:9a9bb9e`. Source and served HTML confirmed. **Browser-level confirmation outstanding — see D5a.** |
| D7 | `app/worker/obj/` committed, containing another developer's absolute paths and an unrelated commit hash | Block 00 | `test_no_build_output_tracked` |
| D8 | `app/.env` symlink pointing into a previous project's secret directory | Block 00 | `test_no_env_symlink` |
| D9 | `app/.env.template` malformed: a bare value line, and trailing comments on value lines | Block 00 | `test_env_template_is_parseable` |
| D11 | `app/docker-compose.deploy.yml` with plaintext credentials, a previous project's RDS and ElastiCache endpoints, and `NODE_TLS_REJECT_UNAUTHORIZED=0` | Block 00 | `test_legacy_deployment_compose_removed` |
| D14 | `/result` without a trailing slash returned HTTP 200 but the browser resolved relative asset paths against `/`, so the page's JavaScript never loaded | Post-Block 03 | `6ea8755`, `HTTPRoute result-redirect`. Externally verified: 301 to `/result/`. |

### Open

| ID | Defect | Demo-visible | Severity | Owner |
|---|---|---|---|---|
| D5a | jQuery was upgraded from the frozen `jquery-latest` (effectively 1.11) to 3.7.1 — a two-major-version jump. The inline script uses `.prop()`, `.html()` and `.css()`, all of which exist in 3.7.1, so it is expected to work, but this has not been confirmed in a browser. | Yes | Medium | Block 04 |
| D5b | `app/vote/templates/index.html:30` loads `jquery.cookie` from a protocol-relative `//cdnjs.cloudflare.com` URL. This resolves to HTTPS and is **not** blocked, so it is not mixed content. It is a legacy pattern and an external runtime dependency. The plugin is also **never called** — the `voter_id` cookie is set server-side by Flask — so it can simply be deleted. | No | Low | Block 04, optional |
| D5c | Font Awesome 4.4.0 is loaded from `maxcdn.bootstrapcdn.com` over HTTPS. Functional, but the page depends on a third-party CDN that has been deprecated for years. | No | Low | Deferred |
| D1 | The `votes` table has no primary key and no unique index on `id`. The worker attempts `INSERT` and only falls back to `UPDATE` on a database error, so with no constraint the insert never conflicts and the `UPDATE` branch is unreachable. A second vote from the same browser **adds a row**, so totals exceed the number of voters. | Yes, if anyone votes twice and compares | Medium | Deferred |
| D2 | `app/worker/Program.cs` pops the vote from Redis, then checks whether the database connection is open. If it is not, it reconnects and continues the loop **without writing the vote**, which is already gone from the queue. The vote is lost. | Rarely | Medium | Deferred |
| D4 | The worker reads neither `DB_PORT` nor `REDIS_PORT`. The Redis connection string is the bare hostname, so the port is not configurable. Works only because both services use default ports. | No | Low | Deferred |
| D6 | `app/vote/requirements.txt` pins nothing: `Flask`, `Redis`, `gunicorn`. Two builds of the same commit can produce different images, which makes the image tag misleading. | No | Medium | Block 09 |
| D10 | All three images run as root. No `USER` instruction, no `securityContext` in any manifest. Would be rejected by the `restricted` Pod Security Standard. | No | Medium | Block 09 |
| D12 | `app/result/package.json` declares `stoppable` and `method-override`, neither of which `server.js` imports. `server.js` requires `pg` twice. The `result` image is single-stage and ships a globally installed `nodemon` to production. | No | Low | Block 09 |
| D13 | `app/vote/app.py` builds the voter identifier with `hex(random.getrandbits(64))[2:-1]`. The `[2:-1]` slice is a Python 2 habit for stripping a trailing `L`; on Python 3 it removes a real hex digit, so the identifier has 4 fewer bits than intended. | No | Low | Deferred |
| D15 | No `/healthz`, `/readyz` or `/metrics` on any service. Readiness probes target `/`, which couples readiness to the application's main path. `vote` and `result` have no liveness probe; `worker` has neither. | No | Medium | Block 09 |

### Not an application defect, tracked here for completeness

| ID | Issue | Owner |
|---|---|---|
| T1 | `tests/unit/test_repository_hygiene.py::test_infrastructure_code_is_not_ignored` asserts on four paths that do not exist — `infra/terraform/env/platform/*` and `deploy/helm/wtt-vote/values-prod.yaml` — left over from the superseded plan. `git check-ignore` returns 1 for any path that is not ignored, existing or not, so the test passes without checking anything. **A test that cannot fail.** | Block 04 |

## Platform gaps affecting the application

| Gap | Effect |
|---|---|
| No backup for PostgreSQL | All voting data is lost if the PVC is deleted. See [blocks/06-data-durability.md](blocks/06-data-durability.md). |
| `gp3` reclaim policy is `Delete` | Deleting the PVC destroys the EBS volume |
| Single replica everywhere | Any pod restart is a brief outage of that function |
| No NetworkPolicy | `vote` can reach PostgreSQL directly although it has no reason to |
| No resource CPU limits | Only memory limits are set. Deliberate and generally correct for CPU, worth stating. |
| No PodDisruptionBudget | A node drain can take down both Traefik and the application simultaneously |
