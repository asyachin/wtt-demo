# Target Architecture

## Goals

| Goal | How it is met |
|---|---|
| Simple | One cluster, one Helm chart, one Terraform root module, one CI workflow per job. |
| Efficient | Spot nodes, one NAT gateway, one shared load balancer, data services in the cluster. |
| Reliable | Health probes, two replicas for stateless services, persistent volumes, tested restore. |
| Reproducible | Everything in Git. Terraform builds the infrastructure, Argo CD builds the state inside the cluster. No manual `kubectl apply` in normal operation. |
| Secure | TLS at the edge, no secrets in Git, non-root containers, least-privilege IAM and RBAC, network policies, image scanning. |

## AWS Layout

Single AWS account. Region `eu-north-1` (Stockholm).

```
VPC 10.60.0.0/16
├── Public subnets   10.60.0.0/20,  10.60.16.0/20   (2 availability zones)
│   ├── Network Load Balancer (created by the Traefik Service of type LoadBalancer)
│   └── NAT gateway (one, in the first availability zone)
└── Private subnets  10.60.64.0/20, 10.60.80.0/20   (2 availability zones)
    └── EKS managed node group: 2 x t3.small, Spot, Amazon Linux 2023
```

| Component | Choice | Reason |
|---|---|---|
| Availability zones | 2 | EKS requires at least 2. A third adds cost with no benefit here. |
| NAT gateways | 1 | One third of the cost of one per zone. A zone failure interrupts outbound traffic only, not inbound. Accepted and documented. |
| Node capacity | Spot | About 70 percent cheaper. The workload tolerates an interruption because all stateless services run two replicas and data services restart onto the same EBS volume. |
| Edge | Network Load Balancer at layer 4, Traefik as the gateway | Routing is expressed as standard Gateway API objects and is testable in `kind`. See [ADR 0015](../adr/0015-traefik-gateway-api.md). |
| Certificates | cert-manager with Let's Encrypt, DNS-01 through Route 53 | An ACM certificate cannot be exported, so Traefik cannot use one. See [ADR 0016](../adr/0016-tls-with-cert-manager.md). |
| Registry | GHCR, not ECR | The source code already lives on GitHub. One identity system, no extra AWS resource. See [ADR 0006](../adr/0006-registry-and-image-tags.md). |
| Secret store | AWS Secrets Manager | Native IAM integration through IRSA, read by External Secrets Operator. See [ADR 0007](../adr/0007-secrets-management.md). |
| Terraform state | S3 bucket with versioning, DynamoDB lock table | Standard, cheap, supports recovery from a bad apply. |

## Cluster Layout

```
EKS cluster: wtt-demo
│
├── cluster-scoped
│   ├── Gateway API CRDs, Standard channel, version pinned
│   └── GatewayClass traefik             controller traefik.io/gateway-controller
│
├── namespace kube-system
│   ├── aws-ebs-csi-driver               EKS add-on
│   ├── external-dns                     installed by Terraform, source gateway-httproute
│   └── metrics-server                   installed by Terraform
│
├── namespace traefik
│   ├── traefik                          2 replicas, installed by Terraform
│   └── Gateway wtt-demo                 listeners 8000 HTTP and 8443 HTTPS
│
├── namespace cert-manager
│   └── cert-manager                     controller, webhook, cainjector
│
├── namespace argocd
│   └── argo-cd                          installed by Terraform, then manages itself
│
├── namespace external-secrets
│   └── external-secrets-operator        installed by Argo CD
│
├── namespace observability
│   ├── kube-prometheus-stack            installed by Argo CD
│   └── grafana                          part of the same chart
│
├── namespace vote-dev                   installed by Argo CD, tracks branch dev
│   ├── vote      2 replicas
│   ├── result    2 replicas
│   ├── worker    1 replica
│   ├── postgres  1 replica, StatefulSet, 10 GiB gp3
│   └── redis     1 replica, StatefulSet, 2 GiB gp3
│
└── namespace vote-prod                  installed by Argo CD, tracks branch main
    └── same objects, production values
```

Terraform owns everything that must exist before Argo CD can run. Argo CD owns everything after that. The boundary is deliberate and is described in [ADR 0005](../adr/0005-gitops-with-argocd.md).

## Traffic Path

```
Browser
  │  TCP, no TLS termination here
  ▼
Network Load Balancer, layer 4, Proxy Protocol v2 enabled
  │     port 80  ──► Traefik entrypoint 8000  (HTTP)
  │     port 443 ──► Traefik entrypoint 8443  (HTTPS)
  ▼
Traefik, namespace traefik, 2 replicas
  │  TLS terminated here, certificate from cert-manager as a Kubernetes Secret
  │  Gateway wtt-demo decides which namespaces may attach a route
  │
  ├── entrypoint 8000: one HTTPRoute with a RequestRedirect filter to https
  │
  └── entrypoint 8443, resolved from the HTTPRoute objects:
        ├── Host wtt-demo.syachin.de
        │     ├── PathPrefix /          ───► Service vote    (port 80)
        │     └── PathPrefix /result    ───► Service result  (port 80)
        │
        └── Host grafana.wtt-demo.syachin.de
              └── PathPrefix /          ───► Service grafana (port 3000)
  │
  ▼  HTTP inside the cluster, between Traefik and the pods
Pods in namespace vote-prod
```

Two entrypoints are required, not a convenience. The NLB operates at layer 4 and adds no `X-Forwarded-Proto`, so a single entrypoint cannot tell an HTTP request from an HTTPS one and a redirect rule would loop. Port 80 and port 443 therefore map to separate entrypoints, and the redirect lives only on the one behind port 80.

Proxy Protocol v2 must be enabled on the NLB target group and on the Traefik entrypoint together. Without it Traefik logs the NLB addresses instead of the client addresses. Enabling it on one side only breaks all traffic.

Routing notes that the Helm chart must respect:

- The `result` service serves its Socket.IO endpoint on the path `/result/socket.io`, not the default `/socket.io`. The `PathPrefix /result` rule therefore covers both the page and the websocket. A rule for `/socket.io` alone would not work.
- The `vote` page is served at `/` and posts to `/`. It must not be placed behind a path prefix without changing the templates.
- The `worker` has no HTTP route. It only exposes a metrics endpoint on port 9090 inside the cluster.

Ownership follows the Gateway API role model, which is the point of using it:

| Object | Owner | Namespace |
|---|---|---|
| `GatewayClass` | platform, in Terraform | cluster-scoped |
| `Gateway`, with `allowedRoutes` by namespace label | platform, in Terraform | `traefik` |
| `HTTPRoute` for `vote` and `result` | application, in the Helm chart | `vote-dev`, `vote-prod` |
| `HTTPRoute` for Grafana | observability | `observability` |
| `ReferenceGrant`, where a route points at another namespace | the backend's owner | the backend's namespace |

DNS is managed by ExternalDNS, with its source set to `gateway-httproute`. It writes the records into the existing Route 53 hosted zone `syachin.de`. The certificate is issued by cert-manager from Let's Encrypt using a DNS-01 challenge in the same hosted zone, and covers `wtt-demo.syachin.de` and `*.wtt-demo.syachin.de`.

The development environment is not published to the internet. It is reached with `kubectl port-forward`, which keeps one public surface and one certificate. See [ADR 0003](../adr/0003-single-cluster-two-namespaces.md).

## Environments

| Property | `vote-dev` | `vote-prod` |
|---|---|---|
| Git branch watched by Argo CD | `dev` | `main` |
| Helm values file | `deploy/helm/wtt-vote/values-dev.yaml` | `deploy/helm/wtt-vote/values-prod.yaml` |
| Image | `ghcr.io/asyachin/wtt-<service>-dev:<tag>` | `ghcr.io/asyachin/wtt-<service>:<tag>` |
| Replicas, stateless services | 1 | 2 |
| Resource requests | small | small, with limits |
| Secrets source | Kubernetes Secret created by External Secrets from AWS Secrets Manager path `/wtt-demo/dev/*` | the same, path `/wtt-demo/prod/*` |
| Public hostname | none | `wtt-demo.syachin.de` |
| Argo CD sync policy | automated, with prune and self-heal | automated, with prune and self-heal |

Both namespaces are isolated from each other by a default-deny network policy. Each has a `ResourceQuota` so that a mistake in development cannot starve production.

## Delivery Flow

```
feature branch
  │  push
  ▼
GitHub Actions: static checks, unit tests, integration tests on Docker Compose
  │  all green
  ▼
pull request into dev, auto-merge
  │
  ▼
GitHub Actions: build each service twice (dev target and prod target),
                one shared tag, Trivy scan, push to GHCR,
                write the tag into values-dev.yaml on branch dev
  │
  ▼
Argo CD syncs namespace vote-dev
  │
  ▼
GitHub Actions: end-to-end tests against vote-dev
  │  green
  ▼
pull request dev -> main, written by hand, copies the same tag into values-prod.yaml
  │  reviewed and merged
  ▼
Argo CD syncs namespace vote-prod
  │
  ▼
GitHub Actions: end-to-end tests against https://wtt-demo.syachin.de
```

No pipeline ever runs `kubectl apply` or `helm upgrade` against the cluster. The only way into the cluster is a Git commit. This is what makes the state auditable and the rollback trivial: revert the commit.

## Data Flow

```
vote (Flask)
  │  RPUSH votes  {"voter_id": "...", "vote": "a" | "b"}
  ▼
Redis  list "votes"
  │  LPOP votes
  ▼
worker (.NET)
  │  INSERT INTO votes (id, vote) ON CONFLICT (id) DO UPDATE
  ▼
PostgreSQL  table "votes"
  │  SELECT vote, COUNT(id) GROUP BY vote,  every second
  ▼
result (Node.js)
  │  Socket.IO event "scores" on path /result/socket.io
  ▼
Browser
```

Redis is a queue, not a store. If Redis loses its data, votes that are still in the queue are lost. PostgreSQL is the system of record and is the only component that is backed up. This is stated explicitly so that nobody later assumes Redis needs a recovery plan.

## Failure Modes and Responses

| Failure | Effect | Response |
|---|---|---|
| One Spot node is reclaimed | Pods reschedule onto the other node. Stateless services keep serving because they have two replicas. | None. The PodDisruptionBudget and the two-replica setting handle it. |
| PostgreSQL pod restarts | The result page stops updating for up to a minute. Votes keep queueing in Redis and are written once the database is back. | None, the worker retries. |
| Redis pod restarts | Votes in flight are lost. New votes work again. | Accepted. Documented in the runbook. |
| Both nodes lost | Full outage. | Terraform recreates the node group. Argo CD restores all workloads. PostgreSQL restores from the latest S3 backup. Drill recorded in Block 13. |
| Bad application release | Wrong behaviour in production. | Revert the promotion commit on `main`. Argo CD rolls back within its sync interval. |
| Bad infrastructure change | Cluster or network broken. | Terraform state is versioned in S3. Roll back the module version and apply. |
| Both Traefik pods lost | Full outage of every public endpoint, including Grafana. The application itself keeps running. | Two replicas with a PodDisruptionBudget and anti-affinity across the two nodes. Recovery is a reschedule. |
| Certificate renewal fails | The site serves an expired certificate roughly 30 days later, and browsers refuse it. | `CertificateRenewalFailed` fires within an hour of a stuck renewal, which leaves 30 days of margin. Runbook section in Block 13. |
| Gateway API CRD version mismatch after an upgrade | Traefik stops serving every route at once, cluster-wide, not per namespace. | CRD versions are pinned in Terraform and the Standard channel only. `experimentalChannel` stays false, which is asserted by a test. |

## Open Risks

| Risk | Current decision |
|---|---|
| One NAT gateway is a single point of failure for outbound traffic. | Accepted for cost. Inbound traffic is unaffected. |
| Spot nodes can be reclaimed at any time, including during a demonstration. | Accepted. Two replicas and fast rescheduling keep the downtime short. A fallback On-Demand node group definition is kept ready but scaled to zero. |
| PostgreSQL runs as a single pod, so an upgrade or a node loss causes a short outage. | Accepted. The application tolerates it. A highly available database is out of scope for a demonstration. |
| The application has no authentication, so anyone can vote repeatedly from different browsers. | Accepted. It is a demonstration workload. A rate limit on the gateway is a stretch goal, and with Traefik it is a route filter rather than a new component. |
| Certificate renewal is now the project's responsibility rather than AWS's, because an ACM certificate cannot be used by Traefik. | Accepted as the price of a portable edge. See [ADR 0016](../adr/0016-tls-with-cert-manager.md). |
| The TLS private key exists in the cluster as a Secret, which it did not with ACM. | Accepted. RBAC limits `get secret`, and the control plane audit log records access. |
| Traefik is a new component in the path of every public request. | Accepted in exchange for routing that is testable in `kind` on every push. See [ADR 0015](../adr/0015-traefik-gateway-api.md). |
| Let's Encrypt rate limits can lock out certificate issuance for a week after enough failed attempts. | Mitigated by using the staging issuer for every first attempt and every drill. |
