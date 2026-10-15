# 0017 — Four Terraform roots instead of one

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-15 |
| Deciders | Alexander Syachin |
| Block | 01 |
| Supersedes | The single-root layout described in the original delivery plan |
| Superseded by | none |
| **Recorded** | **Retrospectively, 2026-10-15, reconstructed from commits `d586dc5` and `5047e0c`. The decision was made during implementation and was not written down at the time. This record describes the reasoning evident in the code; it is not a contemporaneous document.** |

## Context

The original plan specified one Terraform root at `infra/terraform/env/platform/` consuming reusable modules from `infra/terraform/modules/`. Block 01 built four independent roots instead, and `modules/` was created and left empty.

Nothing recorded the change at the time. This record reconstructs it so the layout is explicable rather than looking accidental, and so the consequences are documented.

## Options

| Option | Advantage | Disadvantage |
|---|---|---|
| One root with modules | A single `apply` builds everything. One state file. No cross-root wiring. | One state file for the whole platform. A mistake in a cluster change can damage network state. Slow plans as the project grows. |
| Four roots, state-isolated | Blast-radius isolation. A cluster change cannot touch network state. Fast, focused plans. | A mandatory apply order. Cross-root reads. Reverse-order destroy. Four `init` operations. |
| Terraform workspaces | One codebase, several states | Workspaces separate environments, not layers. Wrong tool for this. |

## Decision

Four roots, each with its own state key in a single versioned S3 bucket:

| Root | State key | Owns |
|---|---|---|
| `bootstrap` | `bootstrap/terraform.tfstate` | The state bucket itself. Local state. Run once. |
| `network` | `network/terraform.tfstate` | VPC, subnets, IGW, NAT, EIP, routes, subnet tags |
| `iam` | `iam/terraform.tfstate` | EKS cluster role, node role, EBS CSI role, cert-manager role and policy, Route 53 record |
| `eks` | `eks/terraform.tfstate` | Cluster, add-ons, node group, Pod Identity associations |

Locking uses native S3 `use_lockfile = true`. There is no DynamoDB table. Cross-root values flow one way through `terraform_remote_state`: `eks` reads `network` and `iam`.

Every root pins the AWS provider to exactly `6.68.0`, constrains Terraform to `>= 1.16.0, < 1.17.0`, and sets `allowed_account_ids`.

## Reasoning

**State isolation is the point.** The `eks` root is the one that changes most often — add-on versions, node sizing, Kubernetes version. Keeping that activity away from the state file that describes the VPC means a mistake there cannot propose destroying a subnet. The NAT Gateway and the VPC are the resources whose accidental replacement would be most disruptive, and they now sit in a state file that is touched rarely.

**S3 native locking replaced DynamoDB** because `use_lockfile` makes a separate lock table unnecessary. One fewer resource to create, pay for and explain.

**Exact provider pinning** rather than `~>`. Combined with the committed lock files, `terraform init` without `-upgrade` reproduces the same provider version, which matters for a project whose selling point is reproducibility.

**`allowed_account_ids` on every provider** means an apply against the wrong account fails immediately rather than creating resources somewhere unexpected. Cheap, and it has caught this class of mistake for many people.

**`prevent_destroy` on the state bucket**, so a careless `terraform destroy` in `bootstrap` cannot remove the state of everything else.

## Consequences

### Positive

- A change to the cluster cannot damage network state.
- Plans are small and fast, and reviewing one is realistic.
- Each layer can be destroyed and rebuilt independently, in order.
- No DynamoDB table to manage.
- Exact provider pinning plus committed lock files make applies reproducible.
- Wrong-account applies fail immediately.

### Negative

- **The apply order is mandatory**: `bootstrap` → `network` → `iam` → `eks`. Nothing enforces it; a reader who ignores it gets confusing `terraform_remote_state` errors.
- **Destroy must run in reverse.** Documented in [../operations/teardown.md](../operations/teardown.md).
- **`terraform_remote_state` requires read access to another root's state**, which contains every attribute of those resources. It is a coarse coupling; a published-outputs mechanism would be finer-grained.
- **Four `init` operations**, four provider downloads, four lock files to keep aligned.
- **`infra/terraform/modules/` is an empty directory**, a leftover from the planned layout. Nothing uses it and it misleads a reader into expecting modules.
- **No root is parameterised by environment.** `dev.tfvars` is the only variable file and `iam` and `eks` rely on variable defaults. A second environment would need either new roots or a redesign.
- **The backend bucket name is a literal** in four files, because Terraform forbids variables in backend configuration. Adapting to another account means editing all four or passing `-backend-config`.

### A consequence that became a real problem

**The Route 53 record is in the `iam` root, and it hardcodes a value Kubernetes generates.**

`infra/terraform/iam/dns-demo.tf` creates the A ALIAS for `wtt-demo.syachin.de`, pointing at the NLB hostname that the Traefik `Service` caused AWS to create. The hostname is written in as a string literal.

Two separate faults:

1. **Wrong root.** A DNS record is not IAM. It belongs in `network` or a root of its own.
2. **Inverted ownership.** Terraform now depends on a value it does not own and cannot compute. If the Traefik `Service` is recreated, AWS issues a new hostname, the record keeps pointing at the old one, and the site goes down with nothing reporting it. `terraform plan` stays empty, because from Terraform's view nothing changed.

It also makes a clean rebuild awkward: on a fresh account the record cannot be created until Traefik exists, so the first `iam` apply either fails on that resource or the resource must be commented out and applied later. See [../operations/reproduce.md](../operations/reproduce.md).

The proper fix is `external-dns`, reading the hostname from the `Gateway` and maintaining the record itself. That moves DNS ownership to Kubernetes, where the load balancer already lives. It is deferred because changing it touches DNS for a live demonstration. Discussion in [../lessons.md](../lessons.md).

### Neutral

- `bootstrap` keeps local state, which is unavoidable: it creates the bucket that would hold it. That state file is not committed and is not critical, since the bucket can be re-imported.
- `single_nat_gateway` exists as a variable whose only effect is a validation requiring it to be `true`. It controls nothing. Harmless, and misleading.

## Verification

```bash
# Each root has an independent backend and state key
grep -A8 'backend "s3"' infra/terraform/*/versions.tf infra/terraform/bootstrap/backend.tf | grep -E 'key|bucket'

# Provider pinned exactly, and account guarded
grep -rn 'version = "= 6.68.0"\|allowed_account_ids' infra/terraform/

# Cross-root reads are one-directional, eks → network and iam
grep -rn 'terraform_remote_state' infra/terraform/

# An empty plan in all three roots is the real proof the code describes reality.
# Never yet recorded; Block 10.
```

## Revisit when

A second environment is needed, which would expose the lack of parameterisation. Or the `terraform_remote_state` coupling becomes a problem, at which point outputs published to SSM Parameter Store or Terraform Cloud would be the finer-grained alternative.

The empty `modules/` directory and the misplaced DNS record should be cleaned up regardless, independently of this decision.
