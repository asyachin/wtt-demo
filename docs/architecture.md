# Implemented architecture

This describes what is deployed as of commit `a4d979f`, 15 October 2026. It is not a design proposal. Where a statement could not be verified from this workstation, it says so.

The original pre-implementation design is preserved in [decisions/initial/](decisions/initial/) and the differences are listed in [reconciliation.md](reconciliation.md).

## Environment model

One application environment is deployed.

| Namespace | Role | State |
|---|---|---|
| `vote-dev` | Serves the public demonstration at `wtt-demo.syachin.de` | Five workloads running |
| `vote-prod` | Created by `k8s/base/namespaces.yaml` | **Empty. Not a production environment.** |

The original plan called for two environments with a promotion process. Only one was built. A promotion process needs GitOps (Block 05) and CI (Block 07) first; documenting one now would describe machinery that does not exist.

Neither namespace carries Pod Security Standard labels, and there are no NetworkPolicy objects. Namespace separation here is organisational, not a security boundary.

## AWS layout

Single AWS account, region `eu-north-1`.

```
VPC 10.42.0.0/16
├── Public subnets   10.42.0.0/24, 10.42.1.0/24      eu-north-1a, eu-north-1b
│   │                tag kubernetes.io/role/elb = 1
│   ├── Network Load Balancer, internet-facing
│   └── NAT Gateway, single, in eu-north-1a
└── Private subnets  10.42.10.0/24, 10.42.11.0/24    eu-north-1a, eu-north-1b
                     tag kubernetes.io/role/internal-elb = 1
    └── EKS managed node group: 2x t3.large, On-Demand, 40 GiB root
```

| Property | Value | Source |
|---|---|---|
| Kubernetes version | 1.36 | `infra/terraform/eks/variables.tf` |
| Node group | min 2, desired 2, max 3, `ON_DEMAND`, `max_unavailable: 1` | `infra/terraform/eks/main.tf` |
| Cluster endpoint | Private and public access, public restricted by CIDR allowlist | `eks/main.tf`, `api_public_access_cidrs` |
| Authentication mode | `API_AND_CONFIG_MAP`, creator admin permissions bootstrapped | `eks/main.tf` |
| Self-managed add-ons | Disabled; add-ons are explicit Terraform resources | `bootstrap_self_managed_addons = false` |
| EKS add-ons | `vpc-cni v1.22.4-eksbuild.3`, `kube-proxy v1.36.0-eksbuild.25`, `coredns v1.14.7-eksbuild.10`, `eks-pod-identity-agent`, `aws-ebs-csi-driver` | `eks/main.tf`, `eks/addons-storage.tf` |

The public cluster endpoint is restricted by a variable validation that rejects `0.0.0.0/0`, so the configuration cannot be applied with an open API endpoint.

### Why nodes are private and the load balancer is public

Worker nodes have no public IP (`map_public_ip_on_launch = false` on the private subnets). Nothing in the cluster is directly reachable from the internet. Inbound traffic arrives only through the NLB, which lives in the public subnets and forwards to node ports inside the VPC. Outbound traffic — image pulls from GHCR, ACME calls to Let's Encrypt, the AWS API — leaves through the NAT Gateway.

One NAT Gateway is a deliberate cost choice. It is a single point of failure for **egress** in one availability zone. Inbound traffic is unaffected, because the NLB spans both zones. A zone failure would interrupt image pulls and certificate renewal, not the serving of already-running pods.

### Why t3.large

Total workload CPU requests are about 400 m across all five application pods, so these nodes are not sized for compute. They are sized for **pod density**. With the AWS VPC CNI, the maximum pods per node is derived from ENI capacity, which is far lower on small instance types. Alongside CoreDNS, `kube-proxy`, the CNI, the EBS CSI controller, Traefik and cert-manager, a smaller instance type does not leave room for the application.

The exact `eni-max-pods` value for this cluster has not been read from the running nodes. Confirm with:

```bash
kubectl get node -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.pods}{"\n"}{end}'
```

`t3.medium` is a plausible smaller option. Changing instance type recycles nodes and briefly interrupts the demonstration, so it is deferred.

## Terraform layout

Four independent roots, each with its own S3 state key. There is no shared root module and `infra/terraform/modules/` is an empty directory.

| Root | State key | Creates | Variables |
|---|---|---|---|
| `bootstrap` | `bootstrap/terraform.tfstate` | The state bucket itself, versioned, AES256, public access blocked, `prevent_destroy` | `bootstrap.tfvars` |
| `network` | `network/terraform.tfstate` | VPC, subnets, IGW, NAT, EIP, route tables, subnet tags | `../dev.tfvars` |
| `iam` | `iam/terraform.tfstate` | EKS cluster role, node role, EBS CSI role, cert-manager role and its Route 53 policy, **and the Route 53 A record** | defaults in `variables.tf` |
| `eks` | `eks/terraform.tfstate` | Cluster, add-ons, node group, cert-manager Pod Identity association | defaults in `variables.tf` |

Locking uses native S3 `use_lockfile = true`. There is no DynamoDB table.

Cross-root wiring is by `terraform_remote_state`: the `eks` root reads `network` outputs for subnet IDs and `iam` outputs for role ARNs. This creates a required apply order and means `terraform destroy` must run in reverse. See [operations/reproduce.md](operations/reproduce.md) and [operations/teardown.md](operations/teardown.md).

Rationale and consequences: [ADR 0017](decisions/0017-terraform-multi-root.md).

### Two known layout problems

1. **The Route 53 record lives in the `iam` root.** `infra/terraform/iam/dns-demo.tf` is not IAM. It belongs in its own root or in `network`.
2. **The record hardcodes a Kubernetes-owned value.** The alias target is the NLB hostname that the Traefik `Service` created:

```hcl
alias {
  name    = "ab6ca8d8903fc411db48922a559fdd15-f9a53d15b6b1bfdf.elb.eu-north-1.amazonaws.com"
  zone_id = "Z1UDT6IFJ4EJM"
}
```

Terraform therefore depends on a value Kubernetes owns. If the Traefik `Service` is deleted and recreated, AWS issues a new NLB with a new hostname, and DNS silently points at a load balancer that no longer exists. Nothing detects this automatically. This is the clearest example in the project of the ownership boundary problem described in [lessons.md](lessons.md), and it is tracked as outstanding work.

### Committed identifiers

`infra/terraform/` contains the AWS account ID `899088266068` and the Route 53 hosted zone ID `Z030020038RZDL2JLFT70` in plain text, across several files. Neither is a credential. Both are accepted as published for a portfolio repository, and the acceptance is recorded here rather than left implicit. No access key, secret, token or private key is committed; see [application.md](application.md#secrets) for how the one application secret is handled.

## Identity model

No static AWS credentials exist anywhere in the cluster or the repository. Two mechanisms are in use.

| Consumer | Mechanism | Scope |
|---|---|---|
| Worker nodes | EC2 instance role `wtt-demo-eks-node-role` | `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryPullOnly`, and `AmazonEKS_CNI_Policy` |
| EBS CSI controller | **Pod Identity**, service account `ebs-csi-controller-sa` | `AmazonEBSCSIDriverPolicy` |
| cert-manager | **Pod Identity**, service account `cert-manager` in namespace `cert-manager` | Custom least-privilege Route 53 policy, below |

Pod Identity associations are declared in Terraform, not configured by hand:

```hcl
# infra/terraform/eks/addons-storage.tf — attached to the add-on itself
pod_identity_association {
  service_account = "ebs-csi-controller-sa"
  role_arn        = data.terraform_remote_state.iam.outputs.ebs_csi_role_arn
}

# infra/terraform/eks/cert-manager-identity.tf — a standalone association
resource "aws_eks_pod_identity_association" "cert_manager" { ... }
```

The trust policy is the same shape for both, and is markedly simpler than the IRSA equivalent: it trusts the service principal `pods.eks.amazonaws.com` with `sts:AssumeRole` and `sts:TagSession`. There is no OIDC provider to create, no issuer URL to template, and no audience condition to get wrong.

Rationale: [ADR 0018](decisions/0018-eks-pod-identity.md).

### The CNI exception

`AmazonEKS_CNI_Policy` is attached to the **node role**, not to a dedicated Pod Identity role. `infra/terraform/iam/main.tf` carries a comment acknowledging this as a temporary bootstrap permission. The effect is that any pod that can reach the node's credentials inherits CNI permissions. It works, and it is not least privilege. Tracked as deferred in [roadmap.md](roadmap.md#deferred-beyond-the-interview).

### cert-manager Route 53 permissions

The DNS-01 solver policy in `infra/terraform/iam/cert-manager.tf` is narrower than the cert-manager documentation suggests, using three IAM condition keys:

| Statement | Action | Restriction |
|---|---|---|
| `ChangeAcmeChallengeTXT` | `route53:ChangeResourceRecordSets` | One hosted zone; record type must be `TXT`; record name must be exactly `_acme-challenge.wtt-demo.syachin.de` |
| `ReadHostedZoneRecords` | `route53:ListResourceRecordSets` | The same single hosted zone |
| `CheckDNSChangeStatus` | `route53:GetChange` | `change/*`, which cannot be narrowed further |

A compromised cert-manager pod can create or delete one TXT record name in one zone. It cannot touch the `A` record that points at the demonstration, and it cannot read or modify any other zone.

## Traffic path

```
Browser
  │  https://wtt-demo.syachin.de
  ▼
Route 53  A ALIAS → NLB hostname          (hardcoded in Terraform, see above)
  ▼
Network Load Balancer, layer 4, internet-facing, two availability zones
  │  resolves to two addresses, one per zone
  │  :80  → Traefik entrypoint web      (currently serves plaintext — see below)
  │  :443 → Traefik entrypoint websecure
  ▼
Traefik v3, namespace traefik, 1 replica
  │  TLS terminates here, using Secret wtt-demo-tls from cert-manager
  │  Gateway "traefik-gateway": listener web :8000 HTTP, websecure :8443 HTTPS
  │  websecure pins hostname wtt-demo.syachin.de
  │  both listeners accept routes from all namespaces
  ▼
HTTPRoute objects in namespace vote-dev
  ├── vote            PathPrefix /                      → Service vote:80
  ├── result          PathPrefix /result/socket.io      → Service result:80  (no rewrite)
  │                   PathPrefix /result + URLRewrite   → Service result:80  (prefix → /)
  └── result-redirect Exact /result + RequestRedirect   → 301 to /result/
  ▼
Pods, plain HTTP inside the cluster
```

### Routing detail that matters

The `result` route has two rules and the order is significant. Gateway API matches the more specific path first, so `/result/socket.io` is evaluated before `/result`.

The `/result/socket.io` rule deliberately has **no** `URLRewrite`. The Node.js service serves its Socket.IO endpoint at the path `/result/socket.io`, so the request must arrive unmodified. The `/result` rule, by contrast, rewrites the prefix to `/`, because the application serves its page and static assets from the root. Applying that rewrite to the websocket path would corrupt it and live updates would stop while the page itself continued to work.

The original design document asserted that a single `/result` prefix rule would cover Socket.IO. That was wrong. The implementation is correct, and the difference is recorded in [reconciliation.md](reconciliation.md).

`result-redirect` exists because of a real browser defect found after Block 03: a request to `/result` without the trailing slash returned the page, but the browser then resolved the page's relative asset paths against `/`, so the JavaScript never loaded. The page appeared to work and returned HTTP 200. Fixed in `6ea8755`.

### Externally verified, 15 October 2026

Checked from a workstation outside AWS:

```
dig wtt-demo.syachin.de              → 13.61.87.220, 13.60.127.160
GET  https://.../                    → 200
GET  https://.../result              → 301 → https://wtt-demo.syachin.de/result/
GET  https://.../result/             → 200
GET  https://.../result/app.js       → 200
GET  https://.../result/socket.io/?EIO=4&transport=polling → 200
GET  http://.../                     → 200          ← no redirect to HTTPS
response headers                     → no HSTS, no X-Frame-Options,
                                        no X-Content-Type-Options; `server: gunicorn`
```

### Two outstanding edge gaps

1. **HTTP is served, not redirected.** All three `HTTPRoute` objects attach to both the `web` and `websecure` listeners, and no route carries a `RequestRedirect` to HTTPS. A request on port 80 is answered in plaintext. Target design and rollback plan: [blocks/04-demo-quality-gate.md](blocks/04-demo-quality-gate.md).
2. **No browser security headers.** No `ResponseHeaderModifier` filter is configured. Same block.

Also unconfigured: Proxy Protocol v2. The NLB operates at layer 4 and adds no `X-Forwarded-For`, so Traefik logs and any future rate limiting see NLB addresses, not client addresses. Enabling it requires a coordinated change on both the `Service` annotation and the Traefik entrypoint; one side alone breaks all traffic. Deferred.

## TLS

| Property | Value |
|---|---|
| Issuer | Let's Encrypt production, via `ClusterIssuer letsencrypt-production` |
| Challenge | DNS-01 through Route 53, solver scoped by `dnsNames` selector |
| Certificate object | `Certificate wtt-demo` in namespace `traefik` |
| Secret | `wtt-demo-tls`, referenced by the `websecure` listener |
| Names | `wtt-demo.syachin.de` only. **Not a wildcard.** |
| Observed validity | 2026-10-14 to 2027-01-12, issuer CN `YR2` |
| Renewal | cert-manager renews automatically at roughly two thirds of lifetime |

A staging issuer and a separate staging `Certificate` exist in `k8s/platform/cert-manager/` and were used first. This is the right sequence: Let's Encrypt production permits only five duplicate certificates per week, and a misconfigured solver exhausts that quota in an afternoon.

Because the challenge is DNS-01 rather than HTTP-01, certificate issuance and renewal do not depend on inbound HTTP reachability. Adding the HTTP-to-HTTPS redirect in Block 04 therefore requires no ACME path exemption. That is a direct benefit of the Block 03 design.

Nothing monitors the certificate. There is no alert on renewal failure, because there is no monitoring stack. A failed renewal would become visible only when the certificate expired, roughly 30 days after cert-manager first tried.

## Storage and persistence

| Property | Value |
|---|---|
| StorageClass | `gp3`, provisioner `ebs.csi.aws.com`, `encrypted: true`, `allowVolumeExpansion: true`, `WaitForFirstConsumer` |
| Reclaim policy | **`Delete`** |
| PostgreSQL | StatefulSet, 1 replica, `postgres:17.11-alpine`, `volumeClaimTemplates` requesting 5 GiB |
| Data path | `PGDATA=/var/lib/postgresql/data/pgdata` on the mounted volume |
| Probes | `pg_isready` for both readiness and liveness |
| Redis | Deployment, 1 replica, `redis:7.4.11-alpine`, `--appendonly no --save ""`, **no volume** |

PostgreSQL survives a pod restart because the EBS volume is detached and reattached to the rescheduled pod. `WaitForFirstConsumer` ensures the volume is created in the availability zone where the pod is actually scheduled; without it, a volume can be created in a zone with no capacity for the pod and the pod stays `Pending` forever.

An EBS volume exists in exactly one availability zone, so the PostgreSQL pod can only ever run in that zone. If that zone is short of capacity, the pod does not start elsewhere.

**Two gaps, both serious:**

- The `gp3` StorageClass uses `reclaimPolicy: Delete`. Deleting the PersistentVolumeClaim — directly, or by deleting the StatefulSet with its PVCs, or by a careless GitOps prune — destroys the EBS volume and all voting data. **PVC deletion safety has not been established.**
- There is no backup. No `pg_dump`, no snapshot schedule, no tested restore.

`reclaimPolicy: Retain` would protect against accidental deletion. It is not a backup: it does not protect against corruption, a bad migration, or deletion of the volume itself. Both are owned by [blocks/06-data-durability.md](blocks/06-data-durability.md).

Redis is intentionally ephemeral. It is a queue between the web tier and the worker, not a store. A Redis restart loses votes that are in flight and not yet written to PostgreSQL. PostgreSQL is the only system of record.

## Ownership boundaries

Knowing which tool owns which object is what makes the platform safe to change.

| Object | Owner | Consequence |
|---|---|---|
| VPC, subnets, NAT, IAM roles, EKS cluster, node group, EKS add-ons | Terraform | Change through `terraform apply` |
| Pod Identity associations | Terraform | Declared in the `eks` root |
| Route 53 A record | Terraform, **but the target value is produced by Kubernetes** | Fragile, see above |
| Gateway API CRDs | **MANUAL** `kubectl apply` | Standard channel `v1.6.1`. Version recorded in `operations/reproduce.md`, not in the repository code. |
| Traefik, including `GatewayClass`, `Gateway` and the NLB | **MANUAL** Helm release, chart `41.7.1` | Values in `k8s/platform/traefik/`. The original install command was not captured and is reconstructed. |
| cert-manager | **MANUAL** Helm release, chart `v1.21.2` from `oci://quay.io/jetstack/charts/cert-manager` | Configuration objects in `k8s/platform/cert-manager/` |
| `ClusterIssuer`, `Certificate` | `kubectl apply` from `k8s/platform/cert-manager/` | In Git |
| Namespaces, StorageClass, PostgreSQL, Redis | `kubectl apply` from `k8s/base/` | In Git |
| Application Deployments, Services, HTTPRoutes | `kubectl apply` from `k8s/apps/dev/` | In Git |
| Secret `postgres-credentials` | **MANUAL**, created outside Git | Never committed; see [application.md](application.md#secrets) |

The NLB is owned by the Traefik `Service`, not by Terraform. `terraform destroy` will not remove it, and deleting the Traefik release will. This reverses the usual teardown intuition and is the first step in [operations/teardown.md](operations/teardown.md).

Three platform components are installed by hand. Their versions are known and recorded — Gateway API CRDs `v1.6.1`, Traefik chart `41.7.1`, cert-manager chart `v1.21.2` — but they live in [operations/reproduce.md](operations/reproduce.md) rather than in the repository code, so no apply enforces them. Bringing them under version control is scope item 05-B in [blocks/05-gitops.md](blocks/05-gitops.md).

## Cost estimate

List-price estimates for `eu-north-1`, not billing data. No invoice has been read. Confirm against Cost Explorer after 24 hours of running.

| Item | Rate | Estimated monthly |
|---|---|---|
| EKS control plane | ~0.10 USD/hour | ~73 USD |
| 2 × `t3.large` On-Demand | ~0.09 USD/hour each | ~133 USD |
| NAT Gateway, hourly | ~0.045 USD/hour | ~33 USD |
| NAT Gateway, data processing | ~0.045 USD/GB | variable, low for this workload |
| Network Load Balancer | hourly plus LCU | ~17 USD |
| EBS: 2 × 40 GiB node volumes + 5 GiB PVC, gp3 | ~0.09 USD/GiB-month | ~8 USD |
| Route 53 hosted zone | 0.50 USD/month | ~1 USD |
| S3 state, data transfer out | usage-based | ~2 USD |
| **Total** | | **~250 to 290 USD/month, about 0.35 USD/hour** |

Dominant drivers are the control plane, the two On-Demand nodes and the NAT Gateway. The three largest reduction levers, none applied:

| Lever | Saving | Cost of applying it |
|---|---|---|
| Spot capacity for the node group | ~70% of node cost | Interruptions; single-replica workloads would restart |
| Smaller instance type | up to ~50% of node cost | Constrained by VPC CNI pod density; recycles nodes |
| Destroy between demonstrations | all hourly charges | The public URL stops working; ~20 minute cold start |

The cheapest effective control is to run the teardown procedure when the interview process ends.

## Failure modes

Assessed from the configuration. Not all have been exercised.

| Failure | Effect | Response | Tested |
|---|---|---|---|
| Vote, result or worker pod restarts | Brief unavailability of that function; single replica each | Kubernetes restarts it | No |
| PostgreSQL pod restarts | Result page stops updating; votes queue in Redis | Volume reattaches, worker retries | **Yes, operator-verified in Block 02** |
| Redis restarts | Votes in flight are lost | Accepted by design | No |
| Traefik pod restarts | **Total outage of the public demo.** One replica, no PodDisruptionBudget. | Kubernetes reschedules | No |
| Node lost | Pods reschedule; PostgreSQL only if the replacement is in its volume's zone | Node group replaces the node | No |
| Traefik `Service` recreated | NLB hostname changes; Route 53 still points at the old one; **silent total outage** | Update the hardcoded alias in `iam/dns-demo.tf` and apply | No |
| Certificate renewal fails | Expiry about 30 days later, then browsers refuse the site | No alerting exists; would be found by chance | No |
| PVC deleted | **Irreversible loss of all voting data** | None. No backup exists. | No |
| Bad manifest applied | Whatever the manifest does | Manual `kubectl apply` of the previous version. No GitOps revert path yet. | No |

Single-replica Traefik and single-replica PostgreSQL are the two components whose loss takes the demonstration down. Neither has redundancy, and that is a conscious scope limit for a demonstration rather than an oversight.
