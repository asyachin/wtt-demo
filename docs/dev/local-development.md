# Local Development

## What You Need

| Tool | Minimum | Already installed on the build host |
|---|---|---|
| Docker with Compose v2 | 24 | yes, 29.8 |
| Python | 3.11 | yes, 3.12 |
| `make` | any | yes |
| `git` | 2.40 | yes |
| `gh` | 2.40 | yes, 2.45 |
| `terraform` | 1.9 | yes, 1.16 |
| `kubectl` | 1.31 | yes, 1.35 |
| `helm` | 3.15 | yes, 3.20 |
| `aws` | 2 | yes |
| `argocd` | 2.11 | yes |
| `kind` | 0.23 | **no, install in Block 05** |
| `trivy` | 0.50 | **no, install in Block 01** |
| `cosign` | 2.2 | **no, install in Block 04** |
| `hadolint`, `yamllint`, `kubeconform`, `tflint`, `checkov`, `gitleaks`, `promtool` | current | **no, install in Block 03** |
| `cmctl`, the cert-manager plugin | current | **no, install in Block 07.** Optional. Every procedure has a `kubectl`-only alternative. |

Install the missing tools when the block that needs them starts, not before. `scripts/install-tools.sh`, written in Block 03, installs all of them and pins their versions so that a laptop and CI run the same binaries.

Two versions are pinned in one place and used by both `kind` and EKS: the Gateway API CRD version and the Traefik chart version. They live in `infra/terraform/env/platform/terraform.tfvars` and are read by `tests/platform/kind-setup.sh`. If the two ever differ, the `kind` tests stop saying anything about production, and a test in Block 07 fails for exactly that reason.

## First Setup

```
git clone git@github.com:asyachin/wttcampusone.git
cd wttcampusone

python3 -m venv .venv
source .venv/bin/activate
pip install -r tests/requirements.txt
```

## Environment Files

| File | What it is | In Git |
|---|---|---|
| `app/.env.template` | The documented list of every key, with no values | yes |
| `app/.env.dev` | A symlink to `~/.secrets/portfolio/app/.env.dev`. Development values for local containers. | no, ignored |
| `app/.env.prod` | A symlink to `~/.secrets/portfolio/app/.env.prod`. Kept for reference only. **Nothing local reads it.** Production values live in AWS Secrets Manager. | no, ignored |
| `app/.env` | **Must not exist.** It was a symlink to the previous project's secret file, and Docker Compose loads it automatically, which silently overrode the intended values. Deleted in Block 00, and `tests/unit/test_repository_hygiene.py::test_no_env_symlink` keeps it deleted. | no |

Always pass the environment file explicitly. Never rely on an implicit `.env`:

```
docker compose --env-file .env.dev up -d
```

Every line of an environment file must be `KEY=VALUE` or a comment on its own line. Two mistakes to avoid, both of which were present in the original files:

```
eu-north-1                       # wrong: no key, breaks compose and source
AWS_REGION=eu-north-1            # right

DB_HOST=db  # Example: some-host  # wrong: some Compose versions keep the comment in the value
# The database host
DB_HOST=db                       # right
```

## Running the Stack

```
cd app
docker compose --env-file .env.dev up -d --build
docker compose --env-file .env.dev ps      # wait until every service is healthy
```

| Service | Local address | Notes |
|---|---|---|
| `vote` | http://localhost:8080 | Submit a vote |
| `result` | http://localhost:8081/result | Live count |
| `vote` metrics | http://localhost:8080/metrics | After Block 02 |
| `result` metrics | http://localhost:8081/metrics | After Block 02 |
| `worker` metrics | http://localhost:9090/metrics | After Block 02 |
| `postgres` | localhost:5432 | Only published for local debugging |
| `redis` | localhost:6379 | The same |

Stop and clean up:

```
docker compose --env-file .env.dev down          # keep the volumes
docker compose --env-file .env.dev down -v       # delete the data as well
```

## The Everyday Commands

```
make lint               # every linter, exactly as CI runs them
make test-unit          # fast, no containers
make test-integration   # brings the stack up, runs the tests, tears it down
make kind-up            # kind cluster with the Gateway API CRDs and Traefik, pinned versions
make test-chart         # helm lint, kubeconform, and the kind tests including routing
make kind-down          # delete the kind cluster
make scan               # trivy on all three images
make ci                 # everything CI runs, in the same order
```

`make ci` is the gate before pushing. If it is green locally and red in CI, the pipeline and the Makefile have drifted, and that is a defect in the pipeline.

`make test-chart` is where the routing is proven: path matching, the websocket on `/result/socket.io`, the HTTP to HTTPS redirect, and the `Gateway` refusing a route from a namespace that is not allowed to attach. All of it runs in `kind` in seconds, with no AWS account involved. That is the practical payoff of [ADR 0015](../adr/0015-traefik-gateway-api.md).

## Debugging the Local Stack

```
# Logs
docker compose --env-file .env.dev logs -f worker
docker compose --env-file .env.dev logs --since 5m

# A shell in a running container
docker compose --env-file .env.dev exec vote sh

# The queue depth, which is the first thing to check when the result page is stuck
docker compose --env-file .env.dev exec redis redis-cli LLEN votes

# The rows in the database
docker compose --env-file .env.dev exec db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'SELECT vote, count(*) FROM votes GROUP BY vote'

# Readiness, and which dependency is unhappy
curl -s localhost:8080/readyz | jq
curl -s localhost:8081/readyz | jq
```

### Common Problems

| Symptom | Likely cause | Check |
|---|---|---|
| The result page shows zero after voting | The worker is not consuming | `LLEN votes` is growing, and the worker log shows a connection error |
| The result page never updates | The browser could not open the websocket | The browser console. The Socket.IO path is `/result/socket.io`, not `/socket.io`. In a cluster this means the route must match `PathPrefix /result`. |
| The "you voted" state does not appear | The vendored jQuery assets are missing | The browser console for a 404 on `/static/vendor/`. Before Block 02 this was caused by a plain `http://` CDN reference. |
| The worker exits at once | The database is not ready, or the password is wrong | The worker log, and whether `--env-file` was passed |
| Compose uses the wrong credentials | An implicit `.env` is being loaded | `ls -la app/.env`. It must not exist. |
| A port is already in use | Another stack is running | `docker ps`, and the `VOTE_PORT` and `RESULT_PORT` values |

## Running Against the Cluster

After Block 06 a kubeconfig is available:

```
aws eks update-kubeconfig --region eu-north-1 --name wtt-demo
kubectl get nodes
```

The development namespace is not published to the internet. Reach it with a port forward:

```
kubectl -n vote-dev port-forward svc/vote 8080:80
kubectl -n vote-dev port-forward svc/result 8081:80
pytest -m e2e --base-url http://localhost:8080
```

Argo CD, Prometheus, and the Traefik dashboard are reached the same way:

```
kubectl -n argocd port-forward svc/argocd-server 8443:443
kubectl -n observability port-forward svc/prometheus-operated 9090:9090
kubectl -n traefik port-forward deploy/traefik 9000:9000     # Traefik dashboard and API
```

Grafana is the one component with a public address, at `https://grafana.wtt-demo.syachin.de`.

Reading the state of the edge, which is the first thing to check when a public address misbehaves:

```
kubectl -n traefik get gateway wtt-demo        # PROGRAMMED must be True
kubectl get httproute -A                       # every route must show an accepted parent
kubectl -n traefik get certificate             # READY must be True
kubectl -n vote-prod describe httproute vote | tail -20
```

## Rules for Working Locally

- Never point a local `Certificate` at the `letsencrypt-prod` issuer while experimenting. Let's Encrypt allows 5 duplicate certificates per week, and a debugging session exhausts that in an afternoon, after which production cannot get a certificate either. Use `letsencrypt-staging`, or a self-signed issuer in `kind`.
- Never run `kubectl apply`, `kubectl edit`, `kubectl scale`, or `helm upgrade` against the cluster to change state. Argo CD reverts it within the next sync, and the cluster would then hold a state that Git does not describe. Change Git instead.
- `kubectl logs`, `get`, `describe`, `exec`, and `port-forward` are fine. Reading is not changing.
- Never run `terraform apply` from a laptop against the platform without opening a pull request with the plan output first.
- Never put a real secret in a file inside the repository, not even for a minute, not even unstaged. `gitleaks` scans the full history, and a value that reached a commit must be rotated whether or not the commit was pushed.
