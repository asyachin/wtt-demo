# Block 01 — AWS Infrastructure

| Field | Value |
|---|---|
| Status | `CLOSED` |
| Branch | `block/01-terraform`, merged as `2192eda` |
| Depends on | Block 00 |
| Next | Block 02 |
| Report type | **Retrospective reconstruction**, written 15 October 2026 from the Terraform code and the commit history |

## Goal

Create the AWS foundation for the platform in Terraform: remote state, network, IAM, an EKS cluster with worker nodes, and persistent storage support. Nothing created by hand in the console.

## Observed implementation

| Commit | Subject | What it created |
|---|---|---|
| `d586dc5` | `feat(infra): provision S3 backend VPC NAT and EKS IAM` | `bootstrap`, `network` and `iam` roots |
| `5047e0c` | `feat(infra): deploy EKS cluster and managed node group` | `eks` root: cluster, add-ons, node group |
| `fd3c7f5` | `feat(k8s): define development and production namespaces` | `k8s/base/namespaces.yaml` |
| `0967c66` | `feat(platform): configure EBS CSI with Pod Identity and gp3 storage` | Pod Identity agent, EBS CSI add-on with a Pod Identity association, `gp3` StorageClass |

### Terraform layout

Four independent roots rather than one. Each has its own S3 state key in a single versioned, encrypted bucket.

| Root | State key | Contents |
|---|---|---|
| `bootstrap` | `bootstrap/terraform.tfstate` | The state bucket itself: versioning, AES256 encryption, public access blocked, `BucketOwnerEnforced`, `prevent_destroy` |
| `network` | `network/terraform.tfstate` | VPC `10.42.0.0/16`, two public and two private subnets across `eu-north-1a` and `eu-north-1b`, IGW, one NAT Gateway with an EIP, route tables, EKS subnet tags |
| `iam` | `iam/terraform.tfstate` | EKS cluster role, node role, EBS CSI role |
| `eks` | `eks/terraform.tfstate` | Cluster 1.36, five add-ons, managed node group |

Locking is native S3 `use_lockfile = true`. No DynamoDB table. Provider pinned exactly at `6.68.0`; Terraform constrained to `>= 1.16.0, < 1.17.0`. Every root sets `allowed_account_ids`, so an apply against the wrong account fails immediately.

Rationale recorded retrospectively in [ADR 0017](../decisions/0017-terraform-multi-root.md).

### Variable validation used as a guard

Three validations encode intent that a comment would not enforce:

- `api_public_access_cidrs` rejects an empty list and rejects `0.0.0.0/0`, so the cluster API cannot be exposed to the internet by configuration.
- `availability_zones`, `public_subnet_cidrs` and `private_subnet_cidrs` must each contain exactly two entries.
- `single_nat_gateway` must be `true`. This one is decorative: it gates nothing, because the NAT count is fixed in the code. Noted as a deferred cleanup.

### Identity

`AmazonEKS_CNI_Policy` is attached to the node role with a code comment marking it as a temporary bootstrap permission to be moved to a dedicated Pod Identity role later. It has not been moved.

The EBS CSI driver uses Pod Identity, declared on the add-on itself:

```hcl
pod_identity_association {
  service_account = "ebs-csi-controller-sa"
  role_arn        = data.terraform_remote_state.iam.outputs.ebs_csi_role_arn
}
```

Rationale recorded retrospectively in [ADR 0018](../decisions/0018-eks-pod-identity.md).

## Acceptance criteria and evidence

The original plan specified static checks (`terraform fmt`, `validate`, `tflint`, `checkov`) and a set of post-apply cluster assertions. There is no record that the static tooling was run, and no test file exists for it. What is evidenced is that the infrastructure exists and that the subsequent blocks depend on it successfully.

| # | Criterion | Verification | Result |
|---|---|---|---|
| 1 | Four roots apply cleanly in dependency order | The cluster exists and Blocks 02 and 03 built on it | Satisfied by consequence |
| 2 | Remote state with locking | `backend "s3"` with `use_lockfile = true` in all four roots | Verified by code inspection |
| 3 | Nodes in private subnets with no public address | `map_public_ip_on_launch = false`; node group uses `private_subnet_ids` only | Verified by code inspection |
| 4 | Cluster API not open to the internet | Variable validation rejects `0.0.0.0/0` | Verified by code inspection |
| 5 | Subnet tags present for load balancer discovery | `kubernetes.io/role/elb` on public, `kubernetes.io/role/internal-elb` on private | Verified by code inspection |
| 6 | `gp3` is available and encrypted | `k8s/base/storage/gp3.yaml` | Verified by code inspection |
| 7 | EBS CSI can provision a volume | PostgreSQL bound a 5 GiB PVC in Block 02 | Satisfied by consequence |
| 8 | Nodes `Ready` | **Requires operator verification** | Not recorded |
| 9 | `terraform plan` empty after apply | **Requires operator verification** | Not recorded |

### Outstanding operator verification

These are the checks a reviewer would reasonably expect. They need cluster and AWS access, which was not available when this report was written:

```bash
kubectl get nodes -o wide
kubectl get node -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.pods}{"\n"}{end}'
kubectl get storageclass
for r in network iam eks; do (cd infra/terraform/$r && terraform plan -detailed-exitcode); done
```

An empty plan in all three roots is the real proof that the code describes the deployed reality. Block 10 covers running this.

## Deviations from plan

| Planned | Actual | Recorded in |
|---|---|---|
| One root `env/platform` plus reusable modules | Four roots; `infra/terraform/modules/` is an empty directory | [ADR 0017](../decisions/0017-terraform-multi-root.md) |
| IRSA | EKS Pod Identity | [ADR 0018](../decisions/0018-eks-pod-identity.md) |
| DynamoDB lock table | Native S3 locking | [ADR 0017](../decisions/0017-terraform-multi-root.md) |
| 2 × `t3.small` Spot | 2 × `t3.large` On-Demand, min 2 max 3 | [../architecture.md](../architecture.md#why-t3large) |
| Kubernetes 1.31+, VPC `10.60.0.0/16` | Kubernetes 1.36, VPC `10.42.0.0/16` | [../architecture.md](../architecture.md#aws-layout) |
| Static validation in CI | No CI exists | Block 07 |

The node sizing deviation has a technical reason rather than being arbitrary: the AWS VPC CNI limits pods per node by ENI capacity, and `t3.small` cannot hold the system pods plus the platform plus the application. See [../lessons.md](../lessons.md).

## Risks and limitations after this block

- Single NAT Gateway: a single point of failure for egress in one availability zone. Inbound traffic is unaffected.
- `AmazonEKS_CNI_Policy` on the node role is not least privilege.
- No static analysis of the Terraform code runs anywhere.
- `terraform destroy` must be run in reverse dependency order because of `terraform_remote_state` coupling. See [../operations/teardown.md](../operations/teardown.md).
- The AWS account ID and hosted zone ID are committed in plain text. Accepted; see [../architecture.md](../architecture.md#committed-identifiers).
- On-Demand `t3.large` nodes are the largest controllable cost item.

## Definition of Done

- [x] Infrastructure applied and serving subsequent blocks
- [x] Remote state with locking
- [x] No secret in the repository
- [x] Branch merged into `dev` as `2192eda`
- [x] Status `CLOSED`
- [ ] **Empty `terraform plan` recorded as evidence — outstanding, Block 10**
