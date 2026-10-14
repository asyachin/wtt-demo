# 0004 — Run PostgreSQL and Redis in the Cluster

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The application needs PostgreSQL as its system of record and Redis as a queue between the web tier and the worker.

The previous project used AWS RDS and ElastiCache. The traces of that are still in the repository: hardcoded endpoints, plain-text credentials, and `NODE_TLS_REJECT_UNAUTHORIZED: "0"` in `app/docker-compose.deploy.yml`, which was evidently added to work around a TLS problem with the managed services.

The worker cannot talk to a managed service properly as written. It resolves the Redis hostname to an IPv4 address and connects by address, which breaks TLS name validation, and it ignores `DB_PORT` entirely. Using managed services would mean fixing all of that in application code first.

The data volume is trivial: one table with two short columns, and a list in Redis that is empty most of the time.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| Containers in the cluster, on EBS volumes | No extra AWS cost. Demonstrates StatefulSet, PersistentVolume, volume expansion, and a tested backup and restore. Reproducible locally with Docker Compose. | A single pod, so an upgrade or a node loss causes a short outage. Backup and patching are the operator's job. |
| AWS RDS and ElastiCache | Managed backups, managed patching, multi-availability-zone if paid for. Demonstrates managed service operation. | 30 to 60 USD per month on the smallest instances. A 15 minute apply for every change. Cannot be reproduced locally. Needs the worker's TLS defects fixed first. |
| RDS in production, containers in development | The most realistic | Two connection paths, two secret shapes, two TLS configurations, and a development environment that cannot reproduce a production database problem |

## Decision

PostgreSQL and Redis run as StatefulSets in each namespace, each with an EBS `gp3` PersistentVolumeClaim. PostgreSQL gets 10 GiB and `reclaimPolicy: Retain`. Redis gets 2 GiB. PostgreSQL is backed up nightly to S3 with `pg_dump`, and the restore procedure is proven by a test.

## Reasoning

The cost argument comes first: 30 to 60 USD per month is a third of the entire budget, spent on a managed service for a table with two columns.

The second argument is stronger. Choosing a managed service hands the interesting work to AWS. Choosing containers keeps it, and the work is exactly what a platform engineer is assessed on: a StatefulSet with a volume claim template, a reclaim policy that does not delete data when the workload is deleted, a backup CronJob with an IRSA role and no stored credential, a restore script, an alert that fires when the backup stops, and a drill that proves the restore works. Block 11 produces eleven tests from that. RDS would produce none of it, because AWS does it instead.

The third argument is honesty about the application. Pointing this worker at ElastiCache with TLS would not work without fixing the address-based connection first. Pretending otherwise is how the previous project ended up with `NODE_TLS_REJECT_UNAUTHORIZED: "0"` committed to a repository.

Redis gets a persistent volume even though it is only a queue. It is 2 GiB and costs nothing, and without it every restart loses the votes in flight.

## Consequences

### Positive

- No managed database cost.
- The persistent storage, backup, and recovery work is done by the project rather than by AWS, and is tested.
- The whole stack runs identically under Docker Compose on a laptop, which is what makes the Block 02 integration tests possible.
- `terraform apply` stays fast, because there is no 15 minute database creation in the path.

### Negative

- PostgreSQL is a single pod. An upgrade, a node loss, or a pod eviction causes an outage of the result page lasting as long as the reschedule and the volume reattachment. The application tolerates it because votes queue in Redis, but the outage is real.
- The accepted data loss window is up to 24 hours, between nightly backups. RDS with point-in-time recovery would make that five minutes.
- An EBS volume exists in one availability zone, so the PostgreSQL pod can only run in that zone. If that zone has no capacity, the pod stays `Pending`. This is the failure mode that is easiest to misdiagnose, so it is written into the runbook.
- Patching PostgreSQL is manual: change the image tag in Git and accept the restart.
- Teardown has to delete the volumes explicitly, because `reclaimPolicy: Retain` keeps them billing after the cluster is gone. This is in the teardown procedure.

### Neutral

- The PostgreSQL and Redis versions are pinned in the Helm values, which means they are visible and chosen rather than whatever the managed service offers.

## Verification

- `test_data_survives_pod_delete` and `test_data_survives_node_drain` in Block 11.
- `test_backup_is_restorable` and `test_full_restore_procedure` in Block 11.
- `test_postgres_storage_class_retains` in Block 11.
- The `BackupJobFailed` alert, proven to fire in Block 11.

## Revisit When

The data becomes something whose loss matters, or the single-pod outage becomes unacceptable. Either one means RDS with a read replica, and the worker's connection handling has to be fixed first.
