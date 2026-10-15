# wtt-demo — Platform Engineering Demonstration

A small voting application running on AWS EKS, built to demonstrate platform engineering practice: infrastructure as code, Kubernetes operations, ingress and TLS, workload identity, GitOps delivery, and a CI pipeline with a security gate.

**Independent portfolio project.** Prepared by Alexander Syachin for a Platform & Systems Engineer interview with WTT CampusONE, 16 October 2026. Not an official WTT CampusONE product, service, or infrastructure.

## Live demonstration

| Endpoint | Purpose |
|---|---|
| https://wtt-demo.syachin.de/ | Voting page — cats or dogs |
| https://wtt-demo.syachin.de/result/ | Live results over Socket.IO |

HTTP redirects to HTTPS. The certificate is issued by Let's Encrypt and renewed automatically.

## What this demonstrates

The application is deliberately small. The engineering around it is the point.

| Capability | How it is done |
|---|---|
| Infrastructure as code | Terraform, four state-isolated roots, S3 remote state with native locking |
| Kubernetes | EKS 1.36, nodes in private subnets, EBS-backed StatefulSet |
| Workload identity | EKS Pod Identity. No static AWS credentials anywhere in the cluster or the repository. |
| Ingress | Kubernetes Gateway API with Traefik. Standard route objects, no vendor annotations. |
| TLS | cert-manager with a Route 53 DNS-01 solver scoped to a single record name |
| GitOps | Argo CD syncs the application workloads from `dev`, with self-heal |
| CI | GitHub Actions: tests, build, Trivy CRITICAL gate, publish to GHCR |
| Delivery process | Feature and release branches, pull requests, versioned releases, per-block acceptance criteria |

## Architecture

One AWS account, region `eu-north-1`. One Kubernetes cluster. One deployed application environment, the `vote-dev` namespace, which serves the public demonstration.

### Layers

| Layer | Component | Implementation | Managed by |
|---|---|---|---|
| DNS | `wtt-demo.syachin.de` | Route 53 A record, alias to the load balancer | Terraform, `iam` root |
| Edge | Load balancer | AWS Network Load Balancer, layer 4, two availability zones | Kubernetes, via the Traefik Service |
| Ingress | Gateway | Traefik, Gateway API. Listener `web` redirects to HTTPS; `websecure` terminates TLS and serves. | Helm, installed manually |
| TLS | Certificate | cert-manager, Let's Encrypt production, DNS-01 challenge | Helm plus manifests in `k8s/platform/cert-manager/` |
| Compute | Kubernetes | EKS 1.36, two `t3.large` On-Demand nodes in private subnets | Terraform, `eks` root |
| Network | VPC `10.42.0.0/16` | Two public and two private subnets, one NAT gateway | Terraform, `network` root |
| Identity | IAM | Pod Identity for the EBS CSI driver and cert-manager | Terraform, `iam` and `eks` roots |
| Application | vote, result, worker | Namespace `vote-dev`, one replica each | **Argo CD**, automatic sync |
| Data | PostgreSQL, Redis | PostgreSQL 17 on a 5 GiB gp3 volume; Redis 7.4 as an in-memory queue | `kubectl apply`, manual |
| Delivery | CI | GitHub Actions, images in GHCR | GitHub |

### Request path

| Step | Hop | Detail |
|---|---|---|
| 1 | Browser → Route 53 | Resolves to two load balancer addresses, one per availability zone |
| 2 | → Network Load Balancer | Layer 4. Port 80 to Traefik `web`, port 443 to Traefik `websecure`. No TLS termination here. |
| 3 | → Traefik | TLS terminates here. Port 80 traffic gets a 301 to HTTPS, preserving path and query. |
| 4 | → Service | `/` to `vote`, `/result` to `result`, `/result/socket.io` to `result` without a path rewrite |
| 5 | → Pod | Plain HTTP inside the cluster |

### Vote path

| Step | From | To | Mechanism |
|---|---|---|---|
| 1 | Browser | `vote` | HTML form POST |
| 2 | `vote` | Redis | `RPUSH` onto the `votes` list |
| 3 | `worker` | Redis | `LPOP`, polling every 100 ms |
| 4 | `worker` | PostgreSQL | `INSERT` into the `votes` table |
| 5 | `result` | PostgreSQL | `SELECT … GROUP BY`, once per second |
| 6 | `result` | Browser | Socket.IO `scores` event |

Redis is a queue, not a store. PostgreSQL is the only system of record.

### Component versions

| Component | Version |
|---|---|
| Kubernetes, EKS | 1.36 |
| Terraform | `>= 1.16.0, < 1.17.0`, AWS provider pinned to `6.68.0` |
| Gateway API CRDs | `v1.6.1`, Standard channel |
| Traefik | chart `41.7.1` |
| cert-manager | chart `v1.21.2`, from `oci://quay.io/jetstack/charts/cert-manager` |
| Argo CD | installed by Helm, values in `k8s/platform/argocd/values.yaml` |
| vote | Python 3.14.8, Flask, gunicorn |
| result | Node.js 22, Express, Socket.IO |
| worker | .NET 8 |
| PostgreSQL / Redis | 17.11-alpine / 7.4.11-alpine |

Full detail, including the identity model, ownership boundaries and cost: [docs/architecture.md](docs/architecture.md).

## Status

| Capability | State |
|---|---|
| Terraform infrastructure, EKS, networking, IAM, Pod Identity | Implemented |
| Five workloads running, PostgreSQL persistent across pod restart | Implemented, operator-verified |
| Gateway API routing, Socket.IO, `/result` to `/result/` redirect | Implemented, externally verified |
| Public HTTPS with a trusted production certificate | Implemented, externally verified |
| HTTP to HTTPS redirect | Implemented, externally verified |
| Self-hosted front-end assets, no external CDN dependency | Implemented |
| GitOps: Argo CD syncing the application Deployments and Services | Implemented, with a deliberately narrow scope |
| CI: tests, image build, Trivy CRITICAL gate, publish to GHCR | Implemented |
| Versioned releases through pull requests | Implemented |
| Browser security headers | **Not implemented** |
| PostgreSQL backup and restore | **Not implemented.** Volume reclaim policy is `Delete`, so data loss is possible and irreversible. |
| Argo CD managing HTTPRoutes, data services, cert-manager, Traefik | Not implemented. Those remain manual. |
| Monitoring, metrics, alerting | Not implemented |
| Non-root containers, Pod Security Standards, NetworkPolicy | Not implemented |

This is a demonstration, not a production system. The gaps above are the reason, and each has an owning block in [docs/roadmap.md](docs/roadmap.md).

## Architectural rationale

| Decision | Reason, and what it costs |
|---|---|
| Data services in the cluster, not RDS or ElastiCache | Keeps the StatefulSet, volume and recovery work inside the project. Cost: single-pod PostgreSQL, no automated backup yet. |
| Gateway API with Traefik, not an ALB with Ingress | Portable, standard route objects; routing is testable without AWS. Cost: Traefik is a component to run, and TLS becomes our responsibility. |
| cert-manager, not ACM | An ACM certificate cannot be exported, so Traefik cannot use one. DNS-01 also issues before any public traffic exists. Cost: renewal is an operational duty. |
| EKS Pod Identity, not IRSA | A three-line trust policy instead of a templated OIDC condition. No credential to leak. Cost: EKS-specific. |
| Four Terraform roots, not one | A cluster change cannot damage network state. Cost: a mandatory apply order and cross-root reads. |
| Private nodes, public load balancer | Nothing in the cluster is directly reachable. One NAT gateway, a deliberate cost choice over per-zone redundancy. |
| Two `t3.large` nodes | Sized for pod density, not CPU: the AWS VPC CNI caps pods per node by ENI capacity. |
| Plain manifests, not a Helm chart | Sixteen objects, one environment. A chart would add templating with nothing to parameterise. |
| Narrow Argo CD scope | Adopting a live system incrementally. Deployments and Services first; routing and data services stay manual until proven. |

Decisions, their current applicability, and the deviations from the original design: [docs/decisions/README.md](docs/decisions/README.md).

## Delivery process

Work is organised into numbered blocks, each with acceptance criteria agreed before implementation and evidence recorded at closure. Changes reach `dev` through pull requests from feature or release branches. Releases are versioned and listed in [CHANGELOG.md](CHANGELOG.md).

| Branch kind | Purpose |
|---|---|
| `feature/*` | New behaviour. Merged by pull request. |
| `fix/*` | Corrections |
| `release/*` | An image tag promotion: one line in a manifest |
| `block/*` | A roadmap block |
| `dev` | Integration branch. Argo CD syncs the application from it. |
| `main` | Released state |

Separating `feature/*` from `release/*` keeps a code change and the deployment of its built image in different pull requests, so a rollback of one does not revert the other. Rollback is a Git revert; this was exercised in `3f9d2a6` and `b5b413a`.

Full rules, including the Definition of Done: [docs/process.md](docs/process.md).

## Cost

Roughly **250 to 290 USD per month**, about **0.35 USD per hour** at list price, dominated by the EKS control plane, two On-Demand nodes and the NAT gateway. Estimates, not billing data. Breakdown and reduction options: [docs/architecture.md](docs/architecture.md#cost-estimate). Teardown, with the ordering traps that otherwise leave resources billing: [docs/operations/teardown.md](docs/operations/teardown.md).

## Documentation

| Document | Content |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | Releases, in order, each linked to its merge commit |
| [docs/architecture.md](docs/architecture.md) | Implemented architecture in full |
| [docs/roadmap.md](docs/roadmap.md) | Delivery blocks, status, acceptance evidence, deferred work |
| [docs/process.md](docs/process.md) | Branching, pull requests, releases, Definition of Done |
| [docs/application.md](docs/application.md) | Workloads, interfaces, and the defect register |
| [docs/operations/reproduce.md](docs/operations/reproduce.md) | Rebuild from an empty AWS account |
| [docs/operations/operate.md](docs/operations/operate.md) | Verification and troubleshooting |
| [docs/operations/teardown.md](docs/operations/teardown.md) | Safe teardown and cost control |
| [docs/decisions/README.md](docs/decisions/README.md) | Decision records and what changed against the original plan |
| [docs/lessons.md](docs/lessons.md) | Operational lessons from the build |

---

**Author:** [Alexander Syachin](https://github.com/asyachin) · **Repository:** `asyachin/wtt-demo` · **Region:** `eu-north-1`
