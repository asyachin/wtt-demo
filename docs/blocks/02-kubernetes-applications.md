# Block 02 — Kubernetes Applications

| Field | Value |
|---|---|
| Status | `CLOSED` |
| Branch | `block/02-kubernetes-app`, merged as `5d29446` |
| Depends on | Block 01 |
| Next | Block 03 |
| Report type | **Retrospective reconstruction**, written 15 October 2026 from the manifests and the commit history |

## Goal

Deploy all five application workloads into the cluster, give PostgreSQL durable storage, route traffic internally through the Gateway API, and stop the application leaking credentials into logs.

## Observed implementation

| Commit | Subject | What it did |
|---|---|---|
| `fa8f5e7` | `feat(k8s): deploy PostgreSQL and Redis in vote-dev` | PostgreSQL StatefulSet with a 5 GiB `gp3` PVC and a headless Service; Redis Deployment with persistence disabled |
| `f0ea1a0` | `build: upgrade Result runtime to Node.js 22` | Rebuilt the `result` image; still the tag running today |
| `f75d7b7` | `fix(worker): prevent PostgreSQL credentials in logs` | Removed the connection-string log line from the worker; rebuilt the image |
| `b940f96` | `feat(k8s): deploy voting app and add credential rotation` | `vote`, `result` and `worker` Deployments and Services; `scripts/rotate_k8s_postgres_password.py` |
| `50ef706` | `feat(k8s): configure Traefik Gateway API routing` | Traefik values, `GatewayClass`, `Gateway`, the `vote` and `result` `HTTPRoute` objects |

### Workloads

Five, one replica each, in namespace `vote-dev`. Full detail in [../application.md](../application.md).

PostgreSQL uses `volumeClaimTemplates` with `storageClassName: gp3`, `PGDATA` pointing inside the mount, and `pg_isready` for both probes. Redis runs with `--appendonly no --save ""` and no volume, deliberately, because it is a queue rather than a store.

### Credential handling

The Secret `postgres-credentials` is created manually and is not present in any manifest. PostgreSQL consumes it with `envFrom: secretRef`; `result` and `worker` reference individual keys with `secretKeyRef`. No manifest contains a credential value.

Rationale recorded retrospectively in [ADR 0020](../decisions/0020-manual-postgres-secret.md).

### Routing

Traefik was installed by Helm, chart `41.7.1`, with values committed to `k8s/platform/traefik/values.yaml`. The install command itself was not recorded, which is a reproducibility gap carried into [Block 05](05-gitops.md) as scope item 05-B.

The chart is configured with only the Gateway API provider enabled; the Ingress and CRD providers are switched off. It creates a `GatewayClass` named `traefik` and a `Gateway` named `traefik-gateway` with two listeners, `web:8000` HTTP and `websecure:8443` HTTPS, both accepting routes from all namespaces.

At this point the Service was `ClusterIP`, so nothing was reachable from outside the cluster. Public exposure came in Block 03.

The `result` route needed two rules, and the reason is specific: the service serves its Socket.IO endpoint at `/result/socket.io`, so that path must reach the backend unmodified, while `/result` must have its prefix rewritten to `/` because the application serves its page from the root. A single rule cannot do both. See [../lessons.md](../lessons.md).

## Acceptance criteria and evidence

| # | Criterion | Verification | Result |
|---|---|---|---|
| 1 | All five workloads reach `Running` | `kubectl -n vote-dev get pods` | **Operator-confirmed** at the time of the work |
| 2 | PostgreSQL binds a PVC | PVC bound and the pod started | Satisfied by consequence |
| 3 | **PostgreSQL data survives a pod restart** | Operator deleted the pod and confirmed the data was intact | **Operator-verified.** The one durability property that was actually tested. |
| 4 | The full vote path works: vote → Redis → worker → PostgreSQL → result | Vote submitted and the count observed changing | **Operator-confirmed** at the time of the work |
| 5 | No credential value in any manifest | All credentials via `secretKeyRef` or `envFrom` | Verified by code inspection |
| 6 | The worker no longer logs the connection string | `f75d7b7`; the `result` equivalent is guarded by `test_database_connection_string_not_logged` | Verified |
| 7 | Gateway and routes accepted | `kubectl get gateway,httproute -A` | **Requires operator verification** — see below |
| 8 | Internal routing reaches both services | Satisfied by consequence in Block 03, when the same routes served public traffic | Satisfied by consequence |

### Outstanding operator verification

Not recorded at the time, and not performable without cluster access:

```bash
kubectl -n vote-dev get pods -o wide
kubectl -n traefik get gateway traefik-gateway -o wide     # PROGRAMMED should be True
kubectl get httproute -A
kubectl -n vote-dev describe httproute result | tail -20   # ResolvedRefs, Accepted
kubectl -n vote-dev get pvc
kubectl -n vote-dev get secret postgres-credentials \
  -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'
```

The last command matters: nothing has confirmed from the cluster that the Secret's key names match what the manifests consume. The application works, which is strong indirect evidence, but it has not been checked directly.

## Deviations from plan

| Planned | Actual | Recorded in |
|---|---|---|
| Helm umbrella chart `deploy/helm/wtt-vote` with `values-dev.yaml` and `values-prod.yaml` | Plain YAML under `k8s/{base,apps,platform}` | [ADR 0019](../decisions/0019-plain-manifests-not-helm.md) |
| AWS Secrets Manager plus External Secrets Operator | One manually created Secret plus a rotation script | [ADR 0020](../decisions/0020-manual-postgres-secret.md) |
| Redis on a 2 GiB PVC | Ephemeral, no volume | [../reconciliation.md](../reconciliation.md) |
| PostgreSQL 10 GiB with reclaim policy `Retain` | 5 GiB with reclaim policy `Delete` | [Block 06](06-data-durability.md) |
| `/healthz`, `/readyz` and `/metrics` on every service, with liveness probes | None. Readiness probes target `/`; `vote` and `result` have no liveness probe; `worker` has neither. | Defect D15, Block 09 |
| One `/result` prefix rule covering Socket.IO | A dedicated higher-precedence rule without a rewrite | **The plan was wrong.** [../lessons.md](../lessons.md) |
| Security context, PodDisruptionBudget, NetworkPolicy, resource quotas, two replicas in production | None | Block 09 |

## Risks and limitations after this block

- **Reclaim policy `Delete` on the `gp3` StorageClass.** Deleting the PVC destroys the volume and all voting data. No backup exists. The highest-severity open risk in the project; [Block 06](06-data-durability.md).
- Single replica for every workload, including Traefik. Any restart is a brief outage.
- All containers run as root. No namespace carries Pod Security labels.
- No NetworkPolicy. `vote` can reach PostgreSQL directly, with no reason to.
- The Secret is a manual object. A cluster rebuild requires an operator to recreate it before the application can start.
- Traefik was installed by hand and the command was not recorded.
- Application defects D1, D2, D4, D13 and D15 remain open; see [../application.md](../application.md#defect-register).

## Definition of Done

- [x] Five workloads running
- [x] PostgreSQL persistence verified across a pod restart by the operator
- [x] Vote path working end to end
- [x] No credential in any manifest
- [x] Branch merged into `dev` as `5d29446`
- [x] Status `CLOSED`
- [ ] **Gateway and route status recorded as evidence — outstanding**
- [ ] **Secret key names confirmed against the manifests — outstanding**
