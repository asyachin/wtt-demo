# 0005 — Deliver With Argo CD, and Draw the Terraform Boundary

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

Something has to put the application into the cluster and keep it there. Two tools are already in the stack and both can do it: Terraform has a Helm provider, and Argo CD exists for exactly this.

Without a clear boundary, the two overlap. Terraform installs a chart, Argo CD also manages it, and each one reverts the other on every run. That failure is common and is unpleasant to debug.

There is also the question of what may change the cluster. A pipeline with cluster credentials can deploy quickly and can also delete a namespace by accident.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| Argo CD for workloads, Terraform for infrastructure | A clear boundary. Drift is corrected continuously. Rollback is `git revert`. No cluster credentials in CI. | Another component to run and to recover. The boundary has to be defined and respected. |
| Terraform for everything, including the application | One tool, one state file | `terraform apply` for every image tag change. No drift correction between applies. State and the cluster diverge silently. CI needs cluster credentials. |
| `helm upgrade` from GitHub Actions | Simple and familiar | CI needs cluster credentials, so a compromised workflow owns the cluster. No drift correction. No record in the cluster of what should be there. |
| Flux instead of Argo CD | Lighter, no user interface to secure | The user interface is useful for showing synchronisation state during an interview |

## Decision

Argo CD manages everything inside the cluster. Terraform manages everything that must exist before Argo CD can run.

The boundary:

| Owned by Terraform | Owned by Argo CD |
|---|---|
| VPC, subnets, NAT gateway, route tables | The application Helm chart in both namespaces |
| EKS cluster, node groups, OIDC provider | `kube-prometheus-stack` and the dashboards and rules |
| EKS add-ons: `vpc-cni`, `coredns`, `kube-proxy`, `aws-ebs-csi-driver` | The External Secrets `ClusterSecretStore` and every `ExternalSecret` |
| AWS Load Balancer Controller, ExternalDNS, External Secrets Operator, Metrics Server | Argo CD's own configuration, after the initial install |
| The four namespaces, with their Pod Security labels | Network policies, quotas, and RBAC inside the namespaces |
| IAM roles for IRSA, the ACM certificate, the S3 buckets | |
| The Argo CD installation itself | |

Both Applications use `syncPolicy.automated` with `prune: true` and `selfHeal: true`. No pipeline holds cluster credentials, and no deployment is performed with `kubectl` or `helm`.

## Reasoning

The boundary rule is simple enough to remember: if Argo CD needs it in order to start, Terraform owns it. Everything else is Argo CD's. The add-ons are on the Terraform side because a cluster with no load balancer controller cannot serve an ingress, and bootstrapping that through Argo CD creates a dependency loop.

`selfHeal` is the feature that makes the claim real. A manual `kubectl scale` is reverted within the sync interval, which means the cluster always matches Git, and `kubectl get` is a trustworthy answer to "what is running". `test_self_heal_reverts_a_manual_change` in Block 08 proves it, and it is one of the six tests that matter most in the plan.

Keeping cluster credentials out of CI is a security decision as much as an architectural one. The pipeline's authority ends at pushing an image and committing a tag. A compromised workflow can publish a bad image, which is bad, but it cannot delete a namespace or read a secret from the cluster.

Argo CD manages its own configuration through the app-of-apps after Terraform installs it. That keeps its configuration in Git too, and it also means Argo CD can be reinstalled from scratch with a single `terraform apply -replace` with no state to recover, because it holds none.

Flux was close. Argo CD was chosen for the user interface, which during an interview is a direct way to show synchronisation state, history, and a diff between Git and the cluster.

## Consequences

### Positive

- The cluster state is auditable: it is whatever Git says, continuously.
- Rollback is `git revert`, and it needs no cluster access.
- Drift is corrected automatically instead of being discovered later.
- No pipeline holds cluster credentials.
- Argo CD can be destroyed and reinstalled without losing anything.

### Negative

- Another component to understand, to monitor, and to recover. The recovery procedure is in the runbook.
- `selfHeal` makes manual intervention during an incident harder: a `kubectl scale` is reverted within minutes. The incident procedures acknowledge this and say to put the value into Git.
- A deployment is not instant. It waits for the Argo CD sync interval, which is minutes rather than seconds.
- Argo CD's own user interface is another thing to secure. It is not published; access is by `kubectl port-forward`.
- The boundary has to be respected by hand. Nothing stops a future `helm_release` in Terraform from fighting with an Argo CD Application. A code review is the only guard.

### Neutral

- The Argo CD `AppProject` limits which repositories, namespaces, and resource kinds are allowed, which is extra configuration that pays for itself the first time a manifest names the wrong namespace.

## Verification

- `test_self_heal_reverts_a_manual_change` in Block 08.
- `test_prune_removes_a_deleted_object` in Block 08.
- `test_rollback_by_revert` in Block 08, which performs a rollback with no manual cluster change.
- `test_no_hardcoded_secrets_in_workflows` in Block 03, and the absence of any cluster credential in any workflow.

## Revisit When

The sync delay becomes a real problem, or the project needs more environments than two, at which point an ApplicationSet replaces the hand-written Applications. Neither changes this decision, only its implementation.
