# Architecture

What is deployed as of `390a119`, 15 October 2026. Not a design proposal. Statements that could not be verified from a workstation are marked as needing operator verification.

The original pre-implementation design is preserved in [decisions/initial/](decisions/initial/); the differences are listed in [decisions/README.md](decisions/README.md).

## Environments

| Namespace | Role | State |
|---|---|---|
| `vote-dev` | Serves the public demonstration | Five workloads running |
| `vote-prod` | Created by `k8s/base/namespaces.yaml` | **Empty. Not a production environment.** |
| `traefik` | Gateway and TLS certificate | Traefik, `Gateway`, `Certificate` |
| `cert-manager` | Certificate issuance | cert-manager controller, webhook, cainjector |
| `argocd` | GitOps controller | Argo CD, not publicly reachable |
| `gitops-demo` | Isolated workload used to prove Argo CD safely | One nginx Deployment plus a ConfigMap |

One application environment is deployed. A second environment with a promotion process needs the CI and GitOps work to be wider than it currently is; documenting one now would describe machinery that does not exist.

No namespace carries Pod Security Standard labels and there are no NetworkPolicy objects. Namespace separation here is organisational, not a security boundary.

## AWS resources

| Resource | Value | Terraform root |
|---|---|---|
| Region | `eu-north-1` | all |
| VPC | `10.42.0.0/16` | `network` |
| Public subnets | `10.42.0.0/24`, `10.42.1.0/24`, tagged `kubernetes.io/role/elb=1` | `network` |
| Private subnets | `10.42.10.0/24`, `10.42.11.0/24`, tagged `kubernetes.io/role/internal-elb=1` | `network` |
| NAT gateway | One, in `eu-north-1a` | `network` |
| EKS cluster | `wtt-demo-eks`, version 1.36 | `eks` |
| Node group | 2 desired, min 2, max 3, `t3.large`, On-Demand, 40 GiB root | `eks` |
| Cluster endpoint | Private and public; public restricted by a CIDR allowlist that rejects `0.0.0.0/0` | `eks` |
| EKS add-ons | `vpc-cni v1.22.4-eksbuild.3`, `kube-proxy v1.36.0-eksbuild.25`, `coredns v1.14.7-eksbuild.10`, `eks-pod-identity-agent`, `aws-ebs-csi-driver` | `eks` |
| State bucket | `wtt-demo-tfstate-…`, versioned, AES256, `prevent_destroy` | `bootstrap` |
| Route 53 record | `wtt-demo.syachin.de` A alias | `iam` |
| Load balancer | Network Load Balancer, internet-facing | **not Terraform** — created by the Traefik Service |

### Why nodes are private and the load balancer is public

Nodes have no public address. Inbound traffic arrives only through the load balancer in the public subnets; outbound traffic — image pulls, ACME calls, the AWS API — leaves through the NAT gateway.

One NAT gateway is a cost choice. It is a single point of failure for **egress** in one availability zone. Inbound traffic is unaffected, because the load balancer spans both zones. A zone failure would interrupt image pulls and certificate renewal, not the serving of running pods.

### Why `t3.large`

Total workload CPU requests are about 400 m, so these nodes are not sized for compute. They are sized for **pod density**: with the AWS VPC CNI each pod consumes a real VPC address from an ENI attached to the node, and the number of addresses is a property of the instance type. With CoreDNS, `kube-proxy`, the CNI, the EBS CSI controller, Traefik, cert-manager, Argo CD and the application pods, a smaller type does not fit.

Confirm the real ceiling from the cluster rather than from a table:

```bash
kubectl get node -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.pods}{"\n"}{end}'
```

Requires operator verification; not yet recorded.

## Terraform layout

Four independent roots, each with its own state key in one versioned bucket. There is no shared root module, and `infra/terraform/modules/` is an empty directory left over from the original plan.

| Root | State key | Creates | Variables |
|---|---|---|---|
| `bootstrap` | `bootstrap/terraform.tfstate` | The state bucket itself. Local state, run once. | `bootstrap.tfvars` |
| `network` | `network/terraform.tfstate` | VPC, subnets, IGW, NAT, EIP, routes, tags | `../dev.tfvars` |
| `iam` | `iam/terraform.tfstate` | Cluster, node, EBS CSI and cert-manager roles; **and the Route 53 record** | defaults |
| `eks` | `eks/terraform.tfstate` | Cluster, add-ons, node group, Pod Identity associations | defaults |

Locking uses native S3 `use_lockfile`; there is no DynamoDB table. The AWS provider is pinned to exactly `6.68.0`, Terraform to `>= 1.16.0, < 1.17.0`, and every root sets `allowed_account_ids` so an apply against the wrong account fails immediately.

Cross-root values flow one way: `eks` reads `network` and `iam` through `terraform_remote_state`. This creates a mandatory apply order and a reverse destroy order. Rationale: [ADR 0017](decisions/0017-terraform-multi-root.md).

### Two known layout problems

| Problem | Detail |
|---|---|
| The Route 53 record lives in the `iam` root | `infra/terraform/iam/dns-demo.tf` is not IAM. It belongs in `network` or its own root. |
| The record hardcodes a Kubernetes-generated value | Its alias target is the load balancer hostname the Traefik Service caused AWS to create, written in as a string literal. Terraform depends on a value it does not own and cannot compute. |

If the Traefik Service is recreated, AWS issues a new load balancer with a new hostname, the record keeps pointing at the old one, and the site goes down with nothing reporting it — `terraform plan` stays empty. This is the clearest example of the ownership boundary problem in [lessons.md](lessons.md), and it is a live fragility rather than a hypothetical one.

### Committed identifiers

`infra/terraform/` contains the AWS account ID and the Route 53 hosted zone ID in plain text. Neither is a credential. Both are accepted as published for a portfolio repository, and the acceptance is recorded here rather than left implicit. No access key, secret, token or private key is committed.

## Identity

No static AWS credentials exist in the cluster or the repository.

| Consumer | Mechanism | Permissions |
|---|---|---|
| Worker nodes | EC2 instance role | `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryPullOnly`, `AmazonEKS_CNI_Policy` |
| EBS CSI controller | Pod Identity, service account `ebs-csi-controller-sa` | `AmazonEBSCSIDriverPolicy` |
| cert-manager | Pod Identity, service account `cert-manager` | Custom Route 53 policy, below |
| GitHub Actions | `GITHUB_TOKEN` | Push to GHCR only. No AWS access. |

Pod Identity trust policies are three lines — a service principal of `pods.eks.amazonaws.com` with `sts:AssumeRole` and `sts:TagSession` — rather than an OIDC federated principal with templated `sub` and `aud` conditions. Associations are declared in Terraform and enumerable with one API call. Rationale: [ADR 0018](decisions/0018-eks-pod-identity.md).

**One exception:** `AmazonEKS_CNI_Policy` is attached to the node role, not to a dedicated Pod Identity role. A code comment marks it as a temporary bootstrap permission. It works and it is not least privilege.

### cert-manager Route 53 permissions

| Statement | Action | Restriction |
|---|---|---|
| `ChangeAcmeChallengeTXT` | `route53:ChangeResourceRecordSets` | One hosted zone; type must be `TXT`; name must be exactly `_acme-challenge.wtt-demo.syachin.de` |
| `ReadHostedZoneRecords` | `route53:ListResourceRecordSets` | The same single zone |
| `CheckDNSChangeStatus` | `route53:GetChange` | `change/*`, which cannot be narrowed because change IDs are generated per request |

A compromised cert-manager pod can manipulate one TXT record name in one zone. It cannot touch the A record that points at the demonstration, and it cannot read or write any other zone.

## Edge and routing

| Hop | Detail |
|---|---|
| Route 53 | A alias to the load balancer. Resolves to two addresses, one per availability zone. |
| Network Load Balancer | Layer 4, no TLS termination. Port 80 to Traefik `web`, port 443 to Traefik `websecure`. |
| Traefik | TLS terminates here, using Secret `wtt-demo-tls`. One replica. |
| Pods | Plain HTTP inside the cluster |

### Gateway and routes

| Object | Namespace | Attaches to | Behaviour |
|---|---|---|---|
| `GatewayClass traefik` | cluster-scoped | — | Controller `traefik.io/gateway-controller` |
| `Gateway traefik-gateway` | `traefik` | — | Listeners `web:8000` HTTP and `websecure:8443` HTTPS, hostname pinned, routes accepted from all namespaces |
| `HTTPRoute http-to-https` | `vote-dev` | `web` | 301 to HTTPS, scheme and port set, path and query preserved |
| `HTTPRoute vote` | `vote-dev` | `websecure` | `PathPrefix /` to Service `vote:80` |
| `HTTPRoute result` | `vote-dev` | `websecure` | `PathPrefix /result/socket.io` to `result:80` with **no** rewrite; `PathPrefix /result` to `result:80` with the prefix rewritten to `/` |
| `HTTPRoute result-redirect` | `vote-dev` | `websecure` | Exact `/result` to 301 `/result/` |

Two routing details that matter:

**Socket.IO needs its own rule.** The result service serves its websocket at `/result/socket.io`, so that path must reach the backend unmodified, while `/result` must have its prefix rewritten because the application serves its page from the root. Gateway API matches the more specific path first. A single merged rule would corrupt the websocket path and break live updates while leaving the page working.

**Two listeners are required, not a convenience.** The load balancer works at layer 4 and adds no `X-Forwarded-Proto`, so a single Traefik entrypoint could not distinguish HTTP from HTTPS and a redirect rule on it would loop. Separate listeners avoid that entirely.

### Externally verified, 15 October 2026

```
dig wtt-demo.syachin.de              → 13.61.87.220, 13.60.127.160
GET  http://…/                       → 301 → https://wtt-demo.syachin.de:443/
GET  http://…/result/?x=1            → 301 → https://wtt-demo.syachin.de:443/result/?x=1
GET  https://…/                      → 200
GET  https://…/result/               → 200
GET  https://…/result/app.js         → 200
response headers                     → no HSTS, no X-Frame-Options,
                                        no X-Content-Type-Options; Server: gunicorn
```

The redirect includes an explicit `:443` because the route sets `port: 443`. Functionally correct and cosmetically untidy; omitting the port would let it be inferred from the scheme.

### Outstanding edge gaps

| Gap | Owner |
|---|---|
| No browser security headers, and the `Server` banner is disclosed | [Block 04](roadmap.md) |
| Proxy Protocol v2 not configured, so Traefik logs load balancer addresses rather than client addresses. Enabling it requires a coordinated change on both the Service annotation and the entrypoint; one side alone breaks all traffic. | Deferred |
| Traefik runs one replica with no PodDisruptionBudget. Its loss is a total outage. | Deferred |

## TLS

| Property | Value |
|---|---|
| Issuer | Let's Encrypt production, `ClusterIssuer letsencrypt-production` |
| Challenge | DNS-01 through Route 53, solver scoped by a `dnsNames` selector |
| Certificate | `Certificate wtt-demo` in namespace `traefik`, Secret `wtt-demo-tls` |
| Names | `wtt-demo.syachin.de` only. Not a wildcard. |
| Observed validity | 2026-10-14 to 2027-01-12, issuer CN `YR2` |
| Renewal | Automatic, at roughly two thirds of lifetime |

A staging issuer and a separate staging certificate exist and were used first. Let's Encrypt production permits only five duplicate certificates per week, and a misconfigured solver exhausts that in an afternoon.

Because the challenge is DNS-01 rather than HTTP-01, issuance and renewal never depend on inbound HTTP, so adding the HTTP-to-HTTPS redirect needed no ACME path exemption.

**Nothing monitors the certificate.** There is no alert on renewal failure, because there is no monitoring. A failed renewal would become visible only at expiry, about 30 days after cert-manager first tried.

## Storage

| Property | Value |
|---|---|
| StorageClass | `gp3`, `ebs.csi.aws.com`, encrypted, `allowVolumeExpansion`, `WaitForFirstConsumer` |
| Reclaim policy | **`Delete`** |
| PostgreSQL | StatefulSet, 1 replica, `postgres:17.11-alpine`, 5 GiB claim |
| Redis | Deployment, 1 replica, `redis:7.4.11-alpine`, `--appendonly no --save ""`, no volume |

PostgreSQL survives a pod restart because the volume detaches and reattaches to the rescheduled pod; operator-verified in Block 02. `WaitForFirstConsumer` ensures the volume is created in the zone where the pod is actually scheduled. A volume exists in exactly one availability zone, so the pod can only ever run there.

**Two serious gaps:**

- `reclaimPolicy: Delete` means deleting the claim destroys the volume and all voting data. PVC deletion safety has not been established.
- There is no backup. No dump, no snapshot schedule, no tested restore.

`Retain` would protect against accidental deletion but is not a backup: it does nothing about corruption, a bad migration, or deletion of the volume itself. Both are owned by [Block 06](roadmap.md).

Redis is intentionally ephemeral. A restart loses votes in flight.

## GitOps

| Property | Value |
|---|---|
| Argo CD | Installed by Helm, `ClusterIP`, `server.insecure: true` behind no public route |
| Access | `kubectl -n argocd port-forward svc/argocd-server 8080:80` |
| Application | `vote-dev-apps`, tracking branch `dev`, path `k8s/apps/dev` |
| Sync policy | `automated`, `selfHeal: true`, **`prune: false`**, `PruneLast=true` |
| AppProject | `vote-dev`: source restricted to this repository, destination to namespace `vote-dev`, resource kinds to `Service` and `apps/Deployment` only |
| Demo application | `gitops-demo`, an isolated nginx workload used to prove the mechanism away from the public demonstration |

### What Argo CD owns, and what it does not

| Managed by Argo CD | Still applied by hand |
|---|---|
| The three application Deployments and Services, from `k8s/apps/dev/applications.yaml` via `kustomization.yaml` | HTTPRoutes in `k8s/apps/dev/` |
| The `gitops-demo` workload | Namespaces, StorageClass, PostgreSQL, Redis in `k8s/base/` |
| | cert-manager issuers and certificates |
| | Traefik and cert-manager Helm releases |
| | Gateway API CRDs |
| | The `postgres-credentials` Secret |

The narrow scope is deliberate. Adoption of a live system was done incrementally: an isolated demo first, then the application Deployments, with `prune` left off so that nothing Argo CD does not know about can be deleted. The `AppProject` whitelist enforces the boundary at the API server rather than by convention.

`prune: false` is also what protects the manually created Secret and the hand-applied data services. Widening the scope is future work and is not scheduled.

## Ownership boundaries

Knowing which tool owns which object is what makes the platform safe to change.

| Object | Owner | Consequence |
|---|---|---|
| VPC, subnets, NAT, IAM, cluster, node group, add-ons, Pod Identity | Terraform | Change through `terraform apply` |
| Route 53 record | Terraform, **but the target value is produced by Kubernetes** | Fragile; see above |
| Load balancer | Kubernetes, via the Traefik Service | `terraform destroy` will not remove it |
| Gateway API CRDs, Traefik, cert-manager | Manual Helm and `kubectl` | Versions recorded in [operations/reproduce.md](operations/reproduce.md), not enforced by code |
| Application Deployments and Services | Argo CD | Change through a commit to `dev` |
| HTTPRoutes, namespaces, storage, data services, issuers | Manual `kubectl apply` | Change by applying a manifest |
| Container images | GitHub Actions, published to GHCR | Built on a push to `dev` |
| `postgres-credentials` Secret | Manual, outside Git | Never committed |

## Delivery pipeline

| Stage | Trigger | Action |
|---|---|---|
| Checks | Every push and every pull request to `dev` | Ruff lint, pytest, `node --check` with `npm ci`, `dotnet build` |
| Version | Push to `dev` | Tag computed as `YYYY.MM.DD-HHMM-build.<run>-a<attempt>-<short sha>` |
| Build | Push to `dev`, after checks pass | `docker buildx` per service, loaded locally, **not pushed yet** |
| Scan | After build | Trivy, `severity: CRITICAL`, `ignore-unfixed: true`, `exit-code: 1` |
| Publish | Only if the scan passes | Push two tags per service: the version and the full commit SHA |

Building and scanning before pushing is the important ordering: a vulnerable image never reaches the registry. This gate has already blocked a release and forced a dependency upgrade; see version 0.7.1 in [../CHANGELOG.md](../CHANGELOG.md). Rationale: [ADR 0021](decisions/0021-ci-image-versioning.md).

Deployment is a separate, deliberate step: a `release/*` branch changes the image tag in `k8s/apps/dev/applications.yaml`, a pull request merges it to `dev`, and Argo CD syncs. CI never deploys.

## Cost estimate

List prices for `eu-north-1`. Estimates, not billing data; no invoice has been read. Confirm against Cost Explorer after 24 hours.

| Item | Rate | Monthly |
|---|---|---|
| EKS control plane | ~0.10 USD/hour | ~73 USD |
| 2 × `t3.large` On-Demand | ~0.09 USD/hour each | ~133 USD |
| NAT gateway, hourly | ~0.045 USD/hour | ~33 USD |
| NAT gateway, data processing | ~0.045 USD/GB | variable, low |
| Network Load Balancer | hourly plus capacity units | ~17 USD |
| EBS, 85 GiB `gp3` | ~0.09 USD/GiB-month | ~8 USD |
| Route 53 zone, S3 state, data transfer | usage | ~3 USD |
| **Total** | | **~250 to 290 USD/month, about 0.35 USD/hour** |

Idle cost is nearly the whole cost: a cluster serving no traffic bills almost the same as a busy one.

| Reduction lever | Saving | Cost of applying it |
|---|---|---|
| Spot node capacity | ~70% of node cost | Interruptions; single-replica workloads restart |
| Smaller instance type | up to ~50% of node cost | Constrained by VPC CNI pod density; recycles nodes |
| Destroy between demonstrations | all hourly charges | The public URL stops working; about 20 minutes to rebuild |

The cheapest effective control is [operations/teardown.md](operations/teardown.md) when the demonstration is no longer needed.

## Failure modes

Assessed from the configuration. Not all have been exercised.

| Failure | Effect | Response | Tested |
|---|---|---|---|
| Application pod restarts | Brief loss of that function; one replica each | Kubernetes restarts it | No |
| PostgreSQL pod restarts | Results stop updating; votes queue in Redis | Volume reattaches, worker retries | **Yes**, Block 02 |
| Redis restarts | Votes in flight are lost | Accepted by design | No |
| Traefik pod restarts | **Total outage of the public demonstration** | Kubernetes reschedules | No |
| Node lost | Pods reschedule; PostgreSQL only within its volume's zone | Node group replaces the node | No |
| Traefik Service recreated | New load balancer hostname; the Route 53 record still points at the old one; **silent total outage** | Update the literal in `iam/dns-demo.tf` and apply | No |
| Certificate renewal fails | Expiry about 30 days later, then browsers refuse the site | No alerting exists | No |
| PVC deleted | **Irreversible loss of all voting data** | None. No backup exists. | No |
| Bad image released | Wrong behaviour in production | `git revert` the release commit; Argo CD syncs | **Yes**, `3f9d2a6` then `eac7c13` |
| Vulnerable image | Never published | Trivy gate fails the build | **Yes**, version 0.7.1 |

Single-replica Traefik and single-replica PostgreSQL are the two components whose loss takes the demonstration down. Neither has redundancy, which is a conscious scope limit for a demonstration.
