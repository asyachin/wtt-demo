# Plan versus implementation

This is the single place where every deviation from the original design is recorded. It exists so that a reader can tell a deliberate change from an oversight, and so that no document has to pretend the plan was followed exactly.

Compiled 15 October 2026 against `dev` at `a4d979f`, by reading the Terraform roots, the Kubernetes manifests, the application source and the Git history.

## Two numbering schemes

The original delivery plan at commit `5898c60` used its own block numbering. The current [roadmap.md](roadmap.md) uses a different one. They must not be conflated.

| Original plan block | Subject | Current equivalent |
|---|---|---|
| 00 Repository bootstrap | Repository hygiene | Block 00, same subject |
| 01 Legacy cleanup and multi-stage images | Image standards | Mostly not done — Block 09 |
| 02 Health, metrics and application defects | Probes, `/metrics`, defect fixes | Not done — defect D15, Block 09 |
| 03 Test harness and CI pipeline | GitHub Actions | Not done — Block 07 |
| 04 Image publishing and auto-merge | GHCR, tag scheme, signing | Partially: images in GHCR, built by hand — Block 07 |
| 05 Helm chart | Umbrella chart | Not done — superseded, [ADR 0019](decisions/0019-plain-manifests-not-helm.md) |
| 06 Terraform: network and EKS | VPC and cluster | Block 01, different layout |
| 07 Terraform: platform add-ons | Gateway, certificates, secrets operator | Split: Blocks 02 and 03, partially manual |
| 08 Argo CD and GitOps bootstrap | GitOps | Block 05, planned |
| 09 Secrets management | Secrets Manager and External Secrets | Not done — [ADR 0020](decisions/0020-manual-postgres-secret.md) |
| 10 Observability | Prometheus and Grafana | Not done — Block 08, optional |
| 11 Data persistence and recovery | Backup and restore | Not done — Block 06 |
| 12 Security hardening | Pod Security, NetworkPolicy | Not done — Block 09, optional |
| 13 Final documentation and demo readiness | Runbooks, drill | Partially: this documentation set, Block 10 |

The current scheme numbers only the blocks that were actually executed or are actually planned. The historical completed blocks 00 to 03 have never been renumbered.

One number did move. GitOps was previously proposed as Block 04. The public demonstration quality gate took that number, and GitOps became Block 05. Only a not-started block was renumbered; nothing completed was touched.

## Deviation matrix

Deviation types: **As planned** · **Different** · **Deferred** · **Not started** · **Superseded**

### Decisions that held

| Original decision | Record | Implementation | Type | Evidence |
|---|---|---|---|---|
| Keep the polyglot application rather than rewriting it | [0002](decisions/initial/0002-keep-polyglot-application.md) | Unchanged. Node runtime upgraded to 22. | As planned | `f0ea1a0` |
| PostgreSQL and Redis in-cluster, not RDS or ElastiCache | [0004](decisions/initial/0004-data-services-in-cluster.md) | StatefulSet with an EBS PVC; Redis as an ephemeral Deployment | As planned | `fa8f5e7` |
| Container images in GHCR | [0006](decisions/initial/0006-registry-and-image-tags.md) | As planned, public packages, no pull secret | As planned | `k8s/apps/dev/applications.yaml` |
| No Ansible | [0010](decisions/initial/0010-no-ansible.md) | None present | As planned | — |
| Domain `wtt-demo.syachin.de` | [0014](decisions/initial/0014-domain-and-dns-zone.md) | Live | As planned | externally verified |
| Routing through the Gateway API with Traefik, not Ingress | [0015](decisions/initial/0015-traefik-gateway-api.md) | `GatewayClass`, one `Gateway`, listeners `web:8000` and `websecure:8443` | As planned | `50ef706` |
| Two Traefik entrypoints so HTTP and HTTPS are separable | [0015](decisions/initial/0015-traefik-gateway-api.md) | Implemented as the `web` and `websecure` listeners | As planned | `k8s/platform/traefik/values.yaml` |
| cert-manager with Let's Encrypt and DNS-01, staging issuer first | [0016](decisions/initial/0016-tls-with-cert-manager.md) | As planned, including the staging-then-production sequence | As planned | `71f0e0a` |
| Least-privilege DNS-01 permissions | [0016](decisions/initial/0016-tls-with-cert-manager.md) | **Exceeded the plan.** Scoped by three IAM condition keys to TXT records with one exact name in one zone. | As planned, better | `infra/terraform/iam/cert-manager.tf` |
| Private worker nodes, public load balancer, two availability zones, single NAT | [0003](decisions/initial/0003-single-cluster-two-namespaces.md) | As planned | As planned | `infra/terraform/network/main.tf` |
| Remote Terraform state in S3 | plan | Four state keys in one versioned, encrypted bucket with `prevent_destroy` | As planned | `infra/terraform/bootstrap/` |

### Decisions implemented differently

| Original decision | Record | Implementation | Type | New record | Evidence |
|---|---|---|---|---|---|
| One Terraform root `env/platform` with reusable modules | plan | Four independent roots — `bootstrap`, `network`, `iam`, `eks` — wired by `terraform_remote_state`. `modules/` is empty. | Different | [ADR 0017](decisions/0017-terraform-multi-root.md) | `infra/terraform/` |
| IRSA for workload identity | plan, [0007](decisions/initial/0007-secrets-management.md) | **EKS Pod Identity** for the EBS CSI driver and cert-manager | Different, better | [ADR 0018](decisions/0018-eks-pod-identity.md) | `0967c66`, `eks/cert-manager-identity.tf` |
| DynamoDB table for state locking | plan | Native S3 locking, `use_lockfile = true` | Different, better | [ADR 0017](decisions/0017-terraform-multi-root.md) | every `versions.tf` |
| Helm umbrella chart `deploy/helm/wtt-vote` with per-environment values | plan | Plain Kubernetes YAML under `k8s/{base,apps,platform}` | Different | [ADR 0019](decisions/0019-plain-manifests-not-helm.md) | `k8s/` |
| AWS Secrets Manager plus External Secrets Operator | [0007](decisions/initial/0007-secrets-management.md) | One manually created Kubernetes Secret, plus rotation scripts | Different | [ADR 0020](decisions/0020-manual-postgres-secret.md) | `b940f96`, `scripts/rotate_k8s_postgres_password.py` |
| Two application environments with a promotion process | [0003](decisions/initial/0003-single-cluster-two-namespaces.md) | One deployed environment, `vote-dev`. `vote-prod` exists and is empty. | Different | [architecture.md](architecture.md#environment-model) | `fd3c7f5` |
| 2 × `t3.small` Spot nodes | plan | 2 × `t3.large` On-Demand, min 2 max 3 | Different | [architecture.md](architecture.md#why-t3large) | `eks/variables.tf` |
| Kubernetes 1.31 or later, VPC `10.60.0.0/16` | plan | Kubernetes **1.36**, VPC `10.42.0.0/16` | Different | [architecture.md](architecture.md#aws-layout) | `dev.tfvars` |
| Wildcard certificate covering `*.wtt-demo.syachin.de` | [0016](decisions/initial/0016-tls-with-cert-manager.md) | Single name, `wtt-demo.syachin.de` | Different | [architecture.md](architecture.md#tls) | externally verified |
| PostgreSQL volume 10 GiB with reclaim policy `Retain` | [0004](decisions/initial/0004-data-services-in-cluster.md) | 5 GiB with reclaim policy **`Delete`** | Different, and a live risk | [Block 06](blocks/06-data-durability.md) | `k8s/base/storage/gp3.yaml` |
| Redis on a 2 GiB PVC | [0004](decisions/initial/0004-data-services-in-cluster.md) | Ephemeral, no volume, persistence disabled | Different, defensible for a queue | [application.md](application.md#redis) | `k8s/base/redis/deployment.yaml` |
| Image tags `<semver>-<timestamp>-g<sha>`, a dev and a prod image per service, cosign signatures, SBOM, Trivy | [0006](decisions/initial/0006-registry-and-image-tags.md) | One image per service, tagged with the short SHA of the commit that produced it, built by hand | Different, much simpler | Block 07 | `vote:9a9bb9e`, `result:f0ea1a0`, `worker:f75d7b7` |
| 186 tests across four layers, one pytest harness | [0012](decisions/initial/0012-testing-strategy.md) | 12 unit tests in one file; markers declared but unused; one test cannot fail | Different — the original scope was unrealistic | Blocks 04 and 10 | `tests/unit/test_repository_hygiene.py` |
| `main` production, `dev` development, auto-merge on green CI | [0013](decisions/initial/0013-branching-and-promotion.md) | All work on `dev`. `main` lags at `5898c60`. Block branches retained. No CI, so no auto-merge. | Different | [process.md](process.md#block-lifecycle) | `git branch -vv` |
| A single `/result` prefix rule covers the Socket.IO path | plan | A dedicated, higher-precedence rule for `/result/socket.io` with **no** `URLRewrite`, because the prefix rewrite would corrupt the websocket path | **The plan was wrong; the implementation is correct** | [lessons.md](lessons.md) | `k8s/apps/dev/httproutes.yaml` |
| Route 53 record fully owned by Terraform | plan | Terraform owns the record, but its alias target is the NLB hostname that the Kubernetes Traefik `Service` generated, hardcoded as a literal | Different, and fragile | [ADR 0017](decisions/0017-terraform-multi-root.md), [lessons.md](lessons.md) | `infra/terraform/iam/dns-demo.tf` |
| Terraform contains no AWS account identifier | plan | Account ID and hosted zone ID are committed in plain text | Different, accepted | [architecture.md](architecture.md#committed-identifiers) | several files |

### Planned and not started

| Original decision | Record | Current state | Owner |
|---|---|---|---|
| Argo CD owns everything inside the cluster | [0005](decisions/initial/0005-gitops-with-argocd.md) | Not installed. Delivery is manual `kubectl apply` and `helm install`. | Block 05 |
| HTTP-to-HTTPS redirect via a `RequestRedirect` filter | [0015](decisions/initial/0015-traefik-gateway-api.md) | Not implemented. Port 80 serves plaintext, externally verified. | Block 04 |
| Browser security headers via `ResponseHeaderModifier` | [0015](decisions/initial/0015-traefik-gateway-api.md) | Not implemented, externally verified absent | Block 04 |
| Proxy Protocol v2 to preserve client addresses | [0015](decisions/initial/0015-traefik-gateway-api.md) | Not configured | Deferred |
| Prometheus and Grafana, with a read-only query API | [0009](decisions/initial/0009-observability.md) | Not installed. `grafana.wtt-demo.syachin.de` does not resolve. | Block 08, optional |
| Multi-stage, non-root, pinned, OCI-labelled images | [0011](decisions/initial/0011-container-build-standards.md) | `vote` and `worker` are multi-stage; `result` is single-stage and ships `nodemon`. All three run as root. Python dependencies unpinned. No labels. | Block 09, optional |
| GitHub Actions CI with linting, tests, build and scanning | [0012](decisions/initial/0012-testing-strategy.md) | None. `.github/workflows/` is an empty directory. | Block 07 |
| Nightly `pg_dump` to S3 with a tested restore | [0004](decisions/initial/0004-data-services-in-cluster.md) | None | Block 06 |
| Pod Security Standards, NetworkPolicy, quotas, PodDisruptionBudget | [0012](decisions/initial/0012-testing-strategy.md), plan | None. Namespaces carry no Pod Security labels. | Block 09, optional |
| Health, readiness and metrics endpoints on every service | plan | None. Readiness probes target `/`. | Block 09 |

### Superseded before implementation

| Original decision | Record | Outcome |
|---|---|---|
| One ALB with ACM and an `IngressGroup` | [0008](decisions/initial/0008-ingress-and-dns.md) | Superseded by [0015](decisions/initial/0015-traefik-gateway-api.md) and [0016](decisions/initial/0016-tls-with-cert-manager.md) during design, before any infrastructure existed. The superseding is recorded in the record itself. |

## Changes discovered during implementation that the plan never anticipated

| Finding | Where it is documented |
|---|---|
| `/result` and `/result/` behave differently in a browser, because relative asset paths resolve against the request path. HTTP 200 did not reveal it. | [lessons.md](lessons.md), fixed in `6ea8755` |
| The vote page loaded jQuery over plain `http://`, blocked as mixed active content on an HTTPS page. The page rendered and returned 200 throughout. | [application.md](application.md#defect-register) D5, fixed in `9a9bb9e` and `a4d979f` |
| `t3.small` is not viable because the AWS VPC CNI caps pods per node by ENI capacity, not by CPU or memory | [lessons.md](lessons.md) |
| Gateway API CRDs, Traefik and cert-manager were installed by hand, outside Terraform and outside any manifest. Versions are now recorded as `v1.6.1`, `41.7.1` and `v1.21.2`, but in prose rather than in code. | [operations/reproduce.md](operations/reproduce.md), scope item 05-B |
| A repository hygiene test asserts on paths from the abandoned layout and therefore cannot fail | [application.md](application.md#not-an-application-defect-tracked-here-for-completeness) T1, Block 04 |
| `jquery.cookie` is loaded on every page view and never called; the cookie is set server-side by Flask | [application.md](application.md#defect-register) D5b |
| The voted-state highlight renders only on the POST response, never after a reload. Any acceptance test written against a reload would be wrong. | [blocks/04-demo-quality-gate.md](blocks/04-demo-quality-gate.md) |
