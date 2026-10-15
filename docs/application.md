# Application

A fork of Docker's `example-voting-app`, carried into this repository from an earlier unrelated project. The application is not the deliverable; it exists to give the platform something real to carry. Defects are fixed when they affect the demonstration or leak credentials, and otherwise recorded here.

State as of `390a119`.

## Workloads

Five workloads in namespace `vote-dev`, one replica each.

| Workload | Runtime | Image | Port | Config | Probes |
|---|---|---|---|---|---|
| `vote` | Python 3.14.8, Flask, gunicorn with 4 workers | `ghcr.io/asyachin/wtt-demo/vote:2026.10.15-1558-build.21-a1-5ccdb9a` | 80 | `REDIS_HOST`, `REDIS_PORT` literal | Readiness on `GET /`. No liveness. |
| `result` | Node.js 22, Express, Socket.IO, `tini` as PID 1 | `…/result:2026.10.15-1626-build.27-a1-8968dc4` | 80 | `PORT`, `PG_HOST`, `PG_PORT` literal; user, password and database from `secretKeyRef` | Readiness on `GET /`. No liveness. |
| `worker` | .NET 8, console application | `…/worker:2026.10.15-1339-build.8-a1-a66f5f2` | none | `REDIS_HOST`, `DB_HOST` literal; credentials from `secretKeyRef` | **None.** No HTTP endpoint to probe. |
| `postgres` | PostgreSQL 17.11-alpine, StatefulSet | upstream | 5432 | All three keys via `envFrom: secretRef` | `pg_isready` for both |
| `redis` | Redis 7.4.11-alpine, Deployment | upstream | 6379 | none | `redis-cli ping` for both |

Resource requests are 50 m CPU and 128 Mi memory for the application services, with a 512 Mi memory limit and no CPU limit. PostgreSQL requests 100 m and 256 Mi with a 1 Gi limit.

### Front end

Both pages are self-hosted. **No external network request is made by either page.**

| Page | Assets | Behaviour |
|---|---|---|
| `vote` | Stylesheet and image served through `url_for('static', …)` | **No JavaScript.** The voted state is rendered server-side with Jinja: `{% if vote == 'a' %}selected{% endif %}`. A plain HTML form POST submits the vote. |
| `result` | Stylesheet, `socket.io.js`, `angular.min.js` and `app.js`, all local, under `<base href="./">` | AngularJS 1.x receives a Socket.IO `scores` event once per second |

The `vote` page is interesting for what it lacks. Because the voted state needs no client-side code, the page cannot be broken by a blocked script, a CDN outage, or a library upgrade. That is how defects D5, D5a, D5b and D5c were all closed at once in v0.8.0.

Note that the voted highlight appears on the POST response only. `vote` is assigned inside `if request.method == "POST"`, so after a page reload the highlight is gone by design. Any acceptance test must check the POST response, not a reload.

## Data flow

| Step | From | To | Mechanism |
|---|---|---|---|
| 1 | Browser | `vote` | HTML form POST, sets a `voter_id` cookie server-side |
| 2 | `vote` | `redis` | `RPUSH` onto the `votes` list |
| 3 | `worker` | `redis` | `LPOP`, polling every 100 ms |
| 4 | `worker` | `postgres` | `INSERT INTO votes (id, vote)` |
| 5 | `result` | `postgres` | `SELECT vote, COUNT(id) … GROUP BY vote`, once per second |
| 6 | `result` | Browser | Socket.IO `scores` event on `/result/socket.io` |

Redis holds no persistence: `--appendonly no --save ""` and no volume. It is a queue, and a restart loses votes in flight. PostgreSQL is the only system of record. The `votes` table is `(id VARCHAR(255), vote VARCHAR(255))` with no primary key — see defect D1.

## Images

Built by GitHub Actions on every push to `dev`, scanned by Trivy before publication, and published to GHCR with two tags: the dated version and the full commit SHA.

```
YYYY.MM.DD-HHMM-build.<run>-a<attempt>-<short sha>
```

`imagePullPolicy: Always` is set on all three. Because the version tags are immutable in practice, this costs a registry round trip on every pod start without a benefit. Harmless, worth tidying.

No image is signed and no software bill of materials is produced. Both are deferred extensions of Block 07.

## Secrets

One application secret.

| Property | Value |
|---|---|
| Name | `postgres-credentials`, namespace `vote-dev` |
| Keys | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| Created | **Manually**, outside Git, by the operator |
| In Git | No. No manifest contains a value, only `secretKeyRef` and `envFrom`. |
| Rotation | `scripts/rotate_k8s_postgres_password.py`, which changes the password inside PostgreSQL and updates the Secret together |

Because the Secret appears in no manifest, Argo CD neither manages nor prunes it. `prune: false` on the Application makes that doubly safe.

A Kubernetes Secret is base64, not encryption. Anyone with `get secret` in `vote-dev` can read the password. There is no RBAC restriction limiting that today.

Rationale for the manual approach: [decisions/0020-manual-postgres-secret.md](decisions/0020-manual-postgres-secret.md).

Confirm the key names without printing values — not yet recorded from the cluster:

```bash
kubectl -n vote-dev get secret postgres-credentials \
  -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'
```

## Local development

`app/docker-compose.yml` runs the full stack with the same PostgreSQL and Redis versions as the cluster. It reads `app/.env.dev`, which is not in Git; `app/.env.template` documents the required keys with no values.

```bash
cd app
docker compose --env-file .env.dev up -d --build
docker compose --env-file .env.dev ps
```

Never rely on an implicit `app/.env`. That file was a symlink into a previous project's secret directory, which Docker Compose loads automatically and which silently overrode the intended values. Removed in Block 00, and `tests/unit/test_repository_hygiene.py::test_no_env_symlink` keeps it removed.

## Tests

Twelve unit tests in `tests/unit/test_repository_hygiene.py`, run by CI on every push and pull request.

```bash
python3 -m pytest tests/ -q
```

They cover repository structure rather than application behaviour: ignore rules, no committed build output, no reference to the previous project, a parseable environment template with no credentials, allow-list `.dockerignore` files per build context, and that infrastructure code is not accidentally ignored.

The last of those was defective until `11b36e6` — it asserted on four paths that did not exist, so `git check-ignore` returned 1 regardless and the test could not fail. It now asserts on the real Terraform roots and manifests, **and asserts each file exists** before checking that it is not ignored, which is what makes it non-vacuous.

There are no integration, platform or end-to-end tests. The `integration`, `e2e` and `platform` markers are declared in `pyproject.toml` and unused.

## Defect register

Verified by reading the source at `390a119`.

### Fixed

| ID | Defect | Fixed in |
|---|---|---|
| D3 | Both `worker` and `result` printed the PostgreSQL connection string, including the password, to standard output | v0.3.0, `f75d7b7`; the `result` case is guarded by `test_database_connection_string_not_logged` |
| D5 | The vote page loaded jQuery over plain `http://`, which browsers block as mixed active content on an HTTPS page, so the voted-state highlight never worked | v0.4.2 pinned it over HTTPS; **v0.8.0 removed the dependency entirely** |
| D5a | jQuery was upgraded from the frozen `jquery-latest` to 3.7.1, a two-major-version jump with upgrade risk | v0.8.0. Moot: there is no jQuery. |
| D5b | `jquery.cookie` was loaded on every page view and never called; the cookie is set server-side | v0.8.0, removed |
| D5c | Font Awesome loaded from a third-party CDN | v0.8.0, removed |
| D7 | `app/worker/obj/` committed, containing another developer's absolute paths and an unrelated commit hash | v0.1.0 |
| D8 | `app/.env` symlink into a previous project's secret directory | v0.1.0 |
| D9 | `app/.env.template` malformed: a bare value line and trailing comments on value lines | v0.1.0 |
| D11 | `app/docker-compose.deploy.yml` with plain-text credentials, a previous project's managed service endpoints and `NODE_TLS_REJECT_UNAUTHORIZED=0` | v0.1.0 |
| D14 | `/result` without a trailing slash returned HTTP 200 but the browser resolved relative asset paths against `/`, so the page's JavaScript never loaded | v0.4.1, `6ea8755`. Reinforced in v0.8.0 by `<base href="./">`. |
| D16 | Critical vulnerabilities in the `result` and `worker` images | v0.7.1, `8625709`. `express` to `^4.22.3`, `StackExchange.Redis` to `2.13.17`, `apt-get upgrade` added to both Dockerfiles. Found by the Trivy gate. |
| T1 | `test_infrastructure_code_is_not_ignored` asserted on paths that did not exist and therefore could not fail | v0.7.0, `11b36e6` |

### Open

| ID | Defect | Demo-visible | Severity | Owner |
|---|---|---|---|---|
| D1 | The `votes` table has no primary key and no unique index on `id`. The worker attempts `INSERT` and only falls back to `UPDATE` on a database error, so with no constraint the insert never conflicts and the fallback is unreachable. A second vote from the same browser **adds a row**, so totals can exceed the number of voters. | Yes, if someone votes twice and compares | Medium | Deferred |
| D2 | The worker pops a vote from Redis, then checks the database connection. If it must reconnect, it continues the loop **without writing that vote**, which is already gone from the queue. The vote is lost. | Rarely | Medium | Deferred |
| D4 | The worker reads neither `DB_PORT` nor `REDIS_PORT`. The Redis connection string is the bare hostname, so the port is not configurable. Works only because both services use default ports. | No | Low | Deferred |
| D6 | `app/vote/requirements.txt` pins nothing: `Flask`, `Redis`, `gunicorn`. Two builds of the same commit can produce different images, which weakens the meaning of an image tag. | No | Medium | Block 09 |
| D10 | All three images run as root. No `USER` instruction, no `securityContext` in any manifest. Would be rejected by the `restricted` Pod Security Standard. | No | Medium | Block 09 |
| D12 | `app/result/package.json` declares `stoppable` and `method-override`, neither imported. `server.js` requires `pg` twice. The image is single-stage and ships a globally installed `nodemon`. | No | Low | Block 09 |
| D13 | `app/vote/app.py` builds the voter identifier with `hex(random.getrandbits(64))[2:-1]`. The slice is a Python 2 habit for stripping a trailing `L`; on Python 3 it removes a real hex digit. | No | Low | Deferred |
| D15 | No `/healthz`, `/readyz` or `/metrics` on any service. Readiness probes target `/`, coupling readiness to the application's main path. `vote` and `result` have no liveness probe; `worker` has none at all, so a stuck worker is never restarted. | No | Medium | Block 09 |

## Platform gaps affecting the application

| Gap | Effect |
|---|---|
| No PostgreSQL backup, and the volume reclaim policy is `Delete` | All voting data is lost irreversibly if the claim is deleted. [Block 06](roadmap.md#next-block). |
| Single replica for every workload | Any restart is a brief outage of that function |
| No NetworkPolicy | `vote` can reach PostgreSQL directly although it has no reason to |
| No PodDisruptionBudget | A node drain can take down Traefik and the application together |
| Argo CD manages Deployments and Services only | A routing change still requires a manual `kubectl apply` |
