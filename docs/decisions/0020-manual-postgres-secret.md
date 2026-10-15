# 0020 — A manually created Secret instead of External Secrets

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-15 |
| Deciders | Alexander Syachin |
| Block | 02 |
| Supersedes | The AWS Secrets Manager and External Secrets Operator design in [ADR 0007](initial/0007-secrets-management.md) |
| Superseded by | none |
| **Recorded** | **Retrospectively, 2026-10-15, reconstructed from commits `b940f96` and `2d1049f`. The decision was made during implementation and was not written down at the time.** |

## Context

[ADR 0007](initial/0007-secrets-management.md) specified AWS Secrets Manager as the store for every running-environment secret, read into the cluster by the External Secrets Operator through an IRSA role, with a `ClusterSecretStore` and one `ExternalSecret` per environment.

Block 02 created a single Kubernetes Secret by hand instead. External Secrets was never installed.

The scope that ADR 0007 was written for has also shrunk. It enumerated eight secrets across two environments plus Grafana, Argo CD and a backup role. The implemented system has **one**: the PostgreSQL credentials. Grafana and Argo CD do not exist, there is no backup job, and the backup role was to use workload identity with no stored credential anyway.

## Options

| Option | Advantage | Disadvantage |
|---|---|---|
| **A manually created Kubernetes Secret** | Nothing to install. Nothing in Git. One object to reason about. | A manual step in every rebuild. Exists only in the cluster: lose the cluster and lose the value. No audit trail. Rotation is a script. |
| AWS Secrets Manager plus External Secrets Operator | The value survives the cluster. IAM audit trail. Rotation is an API call plus a refresh. Scales to many secrets. | A controller, a `ClusterSecretStore`, an IAM role and a CRD set, for one secret. Another component in the critical path: if it fails, new pods cannot start. |
| Sealed Secrets or SOPS in Git | The value is versioned with the code | An encrypted secret in Git is still a secret in Git, and the decryption key becomes the thing to protect. Rotation becomes a commit. |
| Plaintext in a manifest | Trivial | Unacceptable. This is what the imported `docker-compose.deploy.yml` did, and removing it was part of Block 00. |

## Decision

One Kubernetes Secret, `postgres-credentials` in namespace `vote-dev`, created by the operator and never committed.

| Property | Value |
|---|---|
| Keys | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| Consumers | `postgres` via `envFrom: secretRef`; `result` and `worker` via individual `secretKeyRef` entries |
| In Git | No. No manifest contains a value, only references. |
| Creation | **MANUAL.** `kubectl create secret generic`, documented in [../operations/reproduce.md](../operations/reproduce.md) step 9 |
| Rotation | `scripts/rotate_k8s_postgres_password.py` |

ADR 0007's central principle is upheld: **no secret in Git, in a manifest, in a Terraform variable file, or in an image.** Only the mechanism changed.

## Reasoning

**One secret does not justify a controller.** External Secrets Operator would add a deployment, a webhook, a CRD set, a `ClusterSecretStore`, an IAM role and a Pod Identity association, to deliver three key-value pairs. It would also put a new component in the start-up path of the database: if the operator is unhealthy, a new PostgreSQL pod cannot obtain its credentials.

**The principle survives the simplification.** What ADR 0007 was protecting against was a credential in version control. A manually created Secret achieves that completely. The mechanism was never the point.

**Rotation already has a script.** `scripts/rotate_k8s_postgres_password.py` changes the password inside PostgreSQL and updates the Secret together, which is the part that actually matters. Doing only one of the two produces a failure that looks like a network problem: the password inside `PGDATA` is authoritative, so a Secret-only change leaves the application unable to authenticate against a database that still holds the old password. A managed secret store does not remove that coupling; it just moves where the new value is written first.

**A useful property for GitOps.** Because the Secret appears in no manifest, Argo CD will never track it, and Argo CD only prunes resources carrying its own tracking label. An untracked Secret is therefore not a prune candidate, and the Application also runs with `prune: false`, a second independent protection. See [../architecture.md](../architecture.md#gitops).

## Consequences

### Positive

- No secret in Git. Verified by inspection of every manifest and variable file.
- No controller, no CRDs, no additional IAM role for secret delivery.
- Nothing extra in the database's start-up path.
- Rotation is one script that handles both halves of the change.
- Argo CD cannot prune it, because it was never tracked.

### Negative

- **A manual step blocks every rebuild.** [reproduce.md](../operations/reproduce.md) stops at step 9 until an operator creates the Secret. The platform is not reproducible from `terraform apply` plus `kubectl apply` alone, and this is one of the reasons why.
- **The value exists only in the cluster.** Losing the cluster loses the credential. The database would have to be recreated, and since there is no backup either, this compounds the data durability risk tracked in [../roadmap.md](../roadmap.md#next-block): a cluster loss means losing both the data and the credential that opened it.
- **No audit trail.** Nothing records who created or last rotated the value, or when. AWS Secrets Manager would have given that through CloudTrail.
- **No rotation history.** Secrets Manager keeps previous versions, so a bad rotation can be rolled back. Here, a bad rotation is recovered by rotating again.
- **A Kubernetes Secret is base64, not encryption.** Anyone with `get secret` in `vote-dev` reads the password in clear text. There is no RBAC restriction limiting that today, and no NetworkPolicy or Pod Security boundary around it either. Secrets Manager would not change the in-cluster exposure, but it would at least mean the cluster was not the only copy.
- **It does not scale.** A second environment, Grafana, Argo CD and a backup job would make four or five manual Secrets. At that point the controller earns its place.

### Neutral

- Secrets Manager would have cost roughly 0.40 USD per secret per month. Negligible either way.
- Three helper scripts exist: `scripts/pass.py` for generating a password, `scripts/pg_pass_rotation.py` for the local Docker Compose stack, and `scripts/rotate_k8s_postgres_password.py` for the cluster. More scripts than a managed store would need, each small.

## Verification

```bash
# No secret value anywhere in the repository
grep -rniE 'POSTGRES_PASSWORD\s*[:=]\s*\S|password\s*[:=]\s*["'"'"'][^"'"'"']+' \
  k8s/ infra/ app/ --include='*.yaml' --include='*.tf' | grep -v secretKeyRef || echo "none"

# Every credential reaches a pod by reference only
grep -n -A3 'POSTGRES_\|PG_PASSWORD\|DB_PASSWORD' k8s/apps/dev/applications.yaml | grep -E 'secretKeyRef|name:'

# The Secret exists with the expected keys, without printing any value
kubectl -n vote-dev get secret postgres-credentials \
  -o jsonpath='{range $k,$v := .data}{$k}{"\n"}{end}'

# No credential in any application log
for d in vote result worker; do kubectl -n vote-dev logs deployment/$d --tail=200; done \
  | grep -ciE 'password=|POSTGRES_PASSWORD'      # expect 0
```

The two `kubectl` checks need cluster access and have not been recorded. **The key names have never been confirmed from the cluster against what the manifests consume**; the application working is strong indirect evidence but not a direct check.

The template `app/.env.template` is committed and holds keys with no values, which `tests/unit/test_repository_hygiene.py::test_env_template_has_no_credentials` enforces.

## Revisit when

Any of these becomes true:

- A second environment is deployed, making this two or more manual Secrets.
- Grafana, Argo CD or a backup job adds secrets of its own.
- An audit trail for secret access is required.
- The credential must survive a cluster loss.

The first two are the likely triggers, and both follow from Blocks 05, 07 and 08. At that point External Secrets Operator with Pod Identity is the natural implementation, and [ADR 0007](initial/0007-secrets-management.md) already describes the shape it should take.
