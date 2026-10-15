# 0018 — EKS Pod Identity instead of IRSA

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-15 |
| Deciders | Alexander Syachin |
| Block | 01, extended in Block 03 |
| Supersedes | The IRSA approach assumed by the original plan and by [ADR 0007](initial/0007-secrets-management.md) |
| Superseded by | none |
| **Recorded** | **Retrospectively, 2026-10-15, reconstructed from commits `0967c66` and `71f0e0a`. The decision was made during implementation and was not written down at the time.** |

## Context

Two in-cluster components need AWS permissions:

- the **EBS CSI controller**, to create, attach and delete EBS volumes;
- **cert-manager**, to write DNS-01 TXT records in Route 53.

The original plan assumed IAM Roles for Service Accounts throughout. Block 01 used EKS Pod Identity for the EBS CSI driver, and Block 03 used it again for cert-manager. No record was written at the time.

## Options

| Option | Advantage | Disadvantage |
|---|---|---|
| **EKS Pod Identity** | No OIDC provider. Trust policy is a service principal. Role-to-service-account binding is an explicit, auditable resource. Supported natively by the EBS CSI add-on. | Requires the `eks-pod-identity-agent` add-on. EKS-only. Newer, so fewer third-party guides. |
| IRSA | Long-established, every guide uses it, works outside EKS with any OIDC-capable cluster | Needs an IAM OIDC provider per cluster. Trust policy templated with the issuer URL plus exact `sub` and `aud` claims. Failures are opaque. |
| Static access keys in a Secret | Works anywhere | A long-lived credential in the cluster. Rotation is manual. Unacceptable. |
| Node instance role for everything | No per-workload setup | Every pod on the node inherits the permissions. Not least privilege. |

## Decision

EKS Pod Identity for both components. The `eks-pod-identity-agent` add-on is installed by Terraform, and both associations are declared in Terraform rather than configured by hand.

| Component | Namespace | Service account | Role |
|---|---|---|---|
| EBS CSI controller | `kube-system` | `ebs-csi-controller-sa` | `wtt-demo-ebs-csi-role`, with `AmazonEBSCSIDriverPolicy` |
| cert-manager | `cert-manager` | `cert-manager` | `wtt-demo-cert-manager-role`, with a custom least-privilege Route 53 policy |

No static AWS credential exists anywhere in the cluster or the repository.

## Reasoning

**The trust policy is dramatically simpler.** Both roles trust a service principal:

```hcl
principals {
  type        = "Service"
  identifiers = ["pods.eks.amazonaws.com"]
}
actions = ["sts:AssumeRole", "sts:TagSession"]
```

The IRSA equivalent requires a federated principal naming the cluster's OIDC provider ARN, a `StringEquals` condition on `sub` with the exact `system:serviceaccount:<ns>:<name>` string, and a condition on `aud`. Each is a place to make a typo, and a typo produces an `AccessDenied` from inside a controller pod with no indication which of the four fields is wrong. That specific failure consumes an afternoon reliably.

**Binding moves out of the trust policy.** With Pod Identity, which service account may use a role is a separate resource:

```hcl
resource "aws_eks_pod_identity_association" "cert_manager" {
  cluster_name    = "wtt-demo-eks"
  namespace       = "cert-manager"
  service_account = "cert-manager"
  role_arn        = "arn:aws:iam::...:role/wtt-demo-cert-manager-role"
}
```

That is easier to read, easier to review, and easier to audit than a condition block buried in a policy document. `aws eks list-pod-identity-associations` enumerates every binding in one call.

**No OIDC provider to manage.** One fewer IAM resource, and no issuer URL to template into policies.

**First-class support in the EBS CSI add-on.** The association is a nested block on the add-on resource itself, so the driver and its permissions are created together:

```hcl
resource "aws_eks_addon" "ebs_csi" {
  addon_name = "aws-ebs-csi-driver"
  pod_identity_association {
    service_account = "ebs-csi-controller-sa"
    role_arn        = data.terraform_remote_state.iam.outputs.ebs_csi_role_arn
  }
  depends_on = [aws_eks_addon.pod_identity_agent]
}
```

**An association can precede its service account.** The cert-manager association was created by Terraform in Block 01's root, while the service account did not exist until cert-manager was installed by Helm in Block 03. Pod Identity tolerates that: the association sits inert and starts working when the service account appears. With IRSA the ordering is equally tolerant, but the annotation on the service account must be set by the Helm chart, which puts part of the identity configuration into chart values rather than into Terraform.

## Consequences

### Positive

- No static AWS credential in the cluster or the repository.
- No IAM OIDC provider to create or maintain.
- Trust policies are three lines and hard to get wrong.
- Bindings are explicit resources, enumerable with one API call.
- Both associations are in Terraform, so identity is reviewed with the infrastructure.
- An association can be created before its consumer exists, which suits a layered build.

### Negative

- **Requires the `eks-pod-identity-agent` add-on.** If it is absent or unhealthy, no pod receives credentials and every affected controller fails with permission errors that look like policy problems. Both associations declare `depends_on` against it for that reason.
- **EKS-only.** IRSA works on any cluster with an OIDC issuer; Pod Identity does not. This weakens the claim that the patterns transfer to a private-cloud Kubernetes platform. For the AWS-hosted demonstration it is the right choice, and the limitation is stated rather than hidden.
- **Fewer third-party guides.** Most Helm chart documentation, including cert-manager's, still assumes an IRSA annotation on the service account.
- **Diagnosis differs from IRSA.** The pod receives `AWS_CONTAINER_CREDENTIALS_FULL_URI` rather than a projected token file. Anyone debugging by looking for the token volume will conclude nothing is configured. The check is:

```bash
kubectl -n cert-manager exec deploy/cert-manager -- env | grep -i AWS_CONTAINER
```

- **The cert-manager association hardcodes two values.** `cluster_name = "wtt-demo-eks"` is a literal rather than `aws_eks_cluster.main.name`, and the `role_arn` is a literal rather than a remote-state reference, unlike the EBS CSI association in the same root. Inconsistent, and it breaks if the cluster is renamed. Worth tidying.

### Neutral

- The node role still carries `AmazonEKS_CNI_Policy`, marked in a code comment as a temporary bootstrap permission to be moved to its own Pod Identity role. It has not been moved, so one component remains outside this decision's benefit. Tracked as deferred.

## The permissions this made it reasonable to tighten

Because the identity mechanism was simple, effort went into the policy instead. The cert-manager Route 53 policy is narrower than cert-manager's own documentation suggests, using three condition keys:

| Statement | Action | Restriction |
|---|---|---|
| `ChangeAcmeChallengeTXT` | `route53:ChangeResourceRecordSets` | One hosted zone; record type must be `TXT`; record name must be exactly `_acme-challenge.wtt-demo.syachin.de` |
| `ReadHostedZoneRecords` | `route53:ListResourceRecordSets` | The same single hosted zone |
| `CheckDNSChangeStatus` | `route53:GetChange` | `change/*`, which cannot be narrowed because change IDs are generated per request |

A compromised cert-manager pod can create or delete one TXT record name in one zone. It cannot modify the `A` record that points at the demonstration, and it cannot read or write any other zone.

Note the coupling this creates: changing the public hostname requires updating `infra/terraform/iam/cert-manager.tf` as well as the manifests, or issuance fails with `AccessDenied`. That is a correct denial being mistaken for a broken role, and it is called out in [../operations/troubleshoot.md](../operations/troubleshoot.md).

## Verification

```bash
# No static credential in the repository
grep -rniE 'aws_access_key_id|aws_secret_access_key' infra/ k8s/ app/ || echo "none"

# Associations exist and are bound as intended
aws eks list-pod-identity-associations --cluster-name wtt-demo-eks --region eu-north-1

# A pod actually receives credentials
kubectl -n cert-manager exec deploy/cert-manager -- env | grep -i AWS_CONTAINER

# The agent is running
kubectl -n kube-system get pods -l app.kubernetes.io/name=eks-pod-identity-agent

# The Route 53 policy is scoped by condition keys
grep -A20 'cert_manager_route53' infra/terraform/iam/cert-manager.tf
```

Both of the `kubectl` checks need cluster access and have not been recorded. The functional evidence is indirect but strong: the production certificate was issued, which cannot happen unless cert-manager obtained credentials and wrote a TXT record.

## Revisit when

The platform must run on a Kubernetes cluster that is not EKS, which would require IRSA or another mechanism. Or when the CNI permission is moved off the node role, at which point this decision extends to a third component rather than changing.
