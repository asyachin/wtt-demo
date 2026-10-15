# Block 06 — Data Durability and Recovery

| Field | Value |
|---|---|
| Status | `PLANNED` |
| Branch | `block/06-data-durability` |
| Depends on | Block 02 |
| Next | Block 07 |
| Report type | Written before implementation |

## Goal

Make the voting data survivable. Today it is protected by exactly one property — that nobody has deleted the PersistentVolumeClaim — and there is no backup of any kind.

## Current state, accurately

| Fact | Evidence |
|---|---|
| PostgreSQL uses a 5 GiB EBS-backed PVC via `volumeClaimTemplates` | `k8s/base/postgres/statefulset.yaml` |
| The volume is `gp3` and encrypted | `k8s/base/storage/gp3.yaml` |
| **Data survives a pod restart** | Operator-verified in Block 02. The volume detaches and reattaches to the rescheduled pod. |
| The StorageClass sets `reclaimPolicy: Delete` | `k8s/base/storage/gp3.yaml` |
| **PVC deletion safety has not been established** | No test, no protection |
| **No backup exists** | No `pg_dump`, no snapshot schedule, no restore procedure |
| **No restore has ever been performed** | — |
| `allowVolumeExpansion: true`, so the volume can grow | `k8s/base/storage/gp3.yaml` |
| `volumeBindingMode: WaitForFirstConsumer`, so the volume is created in the pod's zone | `k8s/base/storage/gp3.yaml` |

### The risk, stated plainly

With `reclaimPolicy: Delete`, deleting the PersistentVolumeClaim destroys the underlying EBS volume and every vote in the database. There is no backup, so the loss is **irreversible**.

Four realistic paths to that outcome:

1. `kubectl delete pvc` run against the wrong context or namespace.
2. Deleting the StatefulSet with `--cascade` semantics that remove its claims.
3. An Argo CD prune with a wrong `path`, which is why pruning is excluded from [Block 05](05-gitops.md) adoption.
4. Namespace deletion.

The same risk also affects teardown: see [../operations/teardown.md](../operations/teardown.md), where deleting the PVC is a deliberate step and the data loss is intended.

### What `Retain` does and does not do

Changing the reclaim policy to `Retain` means deleting the PVC leaves the PersistentVolume and the EBS volume in place, so the data is recoverable by binding a new claim to the released volume.

**`Retain` is not a backup.** It protects against one failure mode, accidental deletion of the claim. It does nothing about:

- data corruption or a bad schema change,
- deletion of the PersistentVolume or the EBS volume itself,
- an availability zone failure,
- ransomware or malicious deletion,
- the need to inspect data as it was yesterday.

Both protections are required and they are not substitutes for one another. That is why this block has two independent steps.

## Scope

| ID | Item | Deliverable |
|---|---|---|
| 06-A | Protect the existing volume from accidental deletion | The reclaim policy on the existing PersistentVolume changed to `Retain`, and the StorageClass changed for future volumes |
| 06-B | Backup | A scheduled `pg_dump` to S3, with an IAM role via Pod Identity and no stored credential |
| 06-C | Restore | A script, and a restore actually performed with the row count verified |
| 06-D | Retention and verification | A lifecycle rule on the bucket, and a check that the most recent backup is non-empty and recent |

### 06-A is independently deliverable

The reclaim-policy change is a single operation on an existing PersistentVolume. It requires no new infrastructure, causes no downtime, needs no pod restart, and is reversible.

**It is worth executing before the interview regardless of this block's status.** The command is recorded here so it is not improvised:

```bash
# Identify the bound volume
kubectl -n vote-dev get pvc
PV=$(kubectl -n vote-dev get pvc data-postgres-0 -o jsonpath='{.spec.volumeName}')

# Inspect before changing
kubectl get pv "$PV" -o jsonpath='{.metadata.name}{"\t"}{.spec.persistentVolumeReclaimPolicy}{"\n"}'

# Change it
kubectl patch pv "$PV" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'

# Confirm
kubectl get pv "$PV" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}{"\n"}'   # expect Retain
```

Note that editing the StorageClass does **not** change volumes that already exist. The `persistentVolumeReclaimPolicy` is copied onto the PersistentVolume at provisioning time. The existing volume must be patched directly, and the StorageClass must also be changed so future volumes inherit the safer default. Both are needed; doing only the StorageClass is a common and silent mistake.

**Not executed as part of the documentation work.** This document specifies it; an operator runs it.

## Out of scope

| Item | Reason |
|---|---|
| Redis persistence | Deliberately ephemeral. It is a queue, and PostgreSQL is the system of record. Losing in-flight votes is accepted. |
| PostgreSQL high availability or replication | A single pod is an accepted scope limit for a demonstration. |
| Point-in-time recovery, WAL archiving | Disproportionate for a two-column table. `pg_dump` is sufficient. |
| Cross-region backup replication | Cost without benefit here. |
| Monitoring or alerting on backup failure | Needs Block 08. Until then, a silent backup failure is a real exposure, and 06-D mitigates it with a manual check rather than an alert. |

## Prerequisites

- Cluster access.
- Permission to create an S3 bucket and an IAM role in Terraform.
- A current row count, recorded before any restore test, as the comparison baseline:

```bash
kubectl -n vote-dev exec postgres-0 -- \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'SELECT vote, count(*) FROM votes GROUP BY vote ORDER BY vote'
```

## Planned work

1. **06-A** Patch the existing PersistentVolume to `Retain`. Change the StorageClass for future volumes. Both committed to `k8s/base/storage/gp3.yaml`.
2. **06-B** A Terraform-managed S3 bucket, versioned, encrypted, public access blocked, in the `network` or a new `storage` root. An IAM role with `s3:PutObject` scoped to that bucket's prefix, bound by Pod Identity to a dedicated service account. A `CronJob` running `pg_dump -Fc` to `s3://<bucket>/postgres/<timestamp>.dump`, reading database credentials from the existing `postgres-credentials` Secret, with `set -o pipefail` so a failure inside the pipe cannot produce a zero-byte object that looks like success.
3. **06-C** `scripts/restore-postgres.sh`, taking a backup key as its only argument. Then a restore performed for real into a throwaway namespace or a separate database, and the row count compared with the baseline.
4. **06-D** A 30-day lifecycle rule. A documented manual check that the most recent object exists, is recent and is non-empty, since there is no alerting yet.

## Acceptance criteria

| # | Criterion | Verification | Expected |
|---|---|---|---|
| 1 | The existing volume cannot be destroyed by deleting its claim | `kubectl get pv <name> -o jsonpath='{.spec.persistentVolumeReclaimPolicy}'` | `Retain` |
| 2 | Future volumes inherit the safer policy | `kubectl get storageclass gp3 -o jsonpath='{.reclaimPolicy}'`, and the committed manifest | `Retain` in both the cluster and Git |
| 3 | The backup job produces a non-empty object | Trigger the CronJob manually, then `aws s3 ls` | A new object with a plausible, non-zero size |
| 4 | The backup job holds no static credential | Inspect the service account and the Pod Identity association | Pod Identity only, no mounted AWS key |
| 5 | The bucket is private, versioned and encrypted | Terraform resource and `aws s3api get-bucket-*` | All three confirmed |
| 6 | **The backup can actually be restored** | Restore into a throwaway target and compare row counts with the baseline | Counts match. **A backup that has never been restored is not a backup.** |
| 7 | **The documented procedure works as written** | A second person, or the same person on a different day, follows `scripts/restore-postgres.sh` and the runbook with no improvisation | Restore succeeds using only the documented steps. If an undocumented step is needed, the documentation is wrong and that is the defect. |
| 8 | Recovery time is measured, not estimated | Time the restore in criterion 6 | A real figure recorded in this report and in [../operations/troubleshoot.md](../operations/troubleshoot.md) |
| 9 | Data loss window is stated | Derived from the backup schedule | An explicit figure. With a daily backup it is up to 24 hours, and that is a documented acceptance, not an accident. |
| 10 | A stale or failed backup is detectable | The documented manual check in 06-D | Confirms recency and non-zero size. Noted as manual until Block 08. |
| 11 | The demonstration is unaffected throughout | [../operations/verify.md](../operations/verify.md) section 1 | All checks pass |
| 12 | Pod restart persistence still holds | Delete the PostgreSQL pod, confirm the data after it returns | Data intact. Re-verifies the Block 02 property with the new reclaim policy in place. |

Criterion 7 is the one that most often goes unmet. A restore that works because the operator remembered an extra step is a restore that will fail when someone else needs it.

## Risks and limitations

| Risk | Note |
|---|---|
| Patching the PersistentVolume is a live change to a bound volume | Metadata-only. No pod restart, no detach. Reversible. Low risk, but it is a cluster change and belongs to an operator, not to a documentation task. |
| `Retain` leaves volumes billing after teardown | Deliberate trade. Teardown must then delete them explicitly; [../operations/teardown.md](../operations/teardown.md) covers it. |
| A restore test that targets the live database would destroy live data | Restore into a throwaway namespace or a separate database name. Never restore over the running database as a test. |
| No alerting on backup failure | Accepted until Block 08. Mitigated by the manual check in 06-D. |

## Definition of Done

- [ ] Criteria 1 to 12 verified, each with its command and real output recorded
- [ ] 06-A applied to both the existing PersistentVolume and the StorageClass
- [ ] A restore performed for real, with the measured duration recorded
- [ ] The data loss window stated explicitly
- [ ] The restore procedure followed as written, with no undocumented steps
- [ ] No secret added to the repository
- [ ] Documentation updated per [../process.md](../process.md#documentation-update-at-block-closure)
- [ ] Branch merged into `dev`
- [ ] Status set to `CLOSED` here and in [../roadmap.md](../roadmap.md)
