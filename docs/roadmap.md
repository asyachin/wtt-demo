# Roadmap

Baseline: `main` and `dev` at `390a119`, 15 October 2026.

Work is organised into numbered blocks. Each has acceptance criteria agreed before implementation and evidence recorded at closure. Status values are defined in [process.md](process.md#status-values).

Releases and their commits are in [../CHANGELOG.md](../CHANGELOG.md). Deviations from the original plan are in [decisions/README.md](decisions/README.md).

## Blocks

| Block | Purpose | Depends on | Status | Delivered in |
|---|---|---|---|---|
| 00 Repository foundation | Repository structure, ignore rules, hygiene tests, local stack, legacy removal | — | `CLOSED` | v0.1.0, merge `4667c11` |
| 01 AWS infrastructure | State backend, VPC, NAT, IAM, EKS 1.36, node group, EBS CSI, `gp3` | 00 | `CLOSED` | v0.2.0, merge `2192eda` |
| 02 Kubernetes applications | Five workloads, PostgreSQL persistence, Traefik and Gateway API routing | 01 | `CLOSED` | v0.3.0, merge `5d29446` |
| 03 Public HTTPS | cert-manager, least-privilege DNS-01, public load balancer, Route 53 | 02 | `CLOSED` | v0.4.0 `71f0e0a`, fix v0.4.1 `6ea8755` |
| 04 Demo quality gate | Browser-correct behaviour: no blocked content, HTTPS enforced, security headers, repaired test | 03 | **`IN PROGRESS`** | v0.4.2, v0.5.0, v0.8.0 — headers outstanding |
| 05 GitOps with Argo CD | Adopt running workloads without disruption, prove rollback by Git | 04 partial | `CLOSED` | v0.6.0, `8ac5789` |
| 06 Data durability | Protect the volume from accidental deletion, then a tested backup and restore | 02 | `PLANNED` | — |
| 07 CI pipeline | Tests, image build, vulnerability gate, publish to GHCR | 05 | `CLOSED` | v0.7.0, PR #1 |
| 08 Observability | Metrics and alerting, scoped to what is genuinely useful at this size | 05 | `OPTIONAL` | — |
| 09 Security hardening | Non-root containers, Pod Security Standards, NetworkPolicy, pinned dependencies, health endpoints | 04, 07 | `OPTIONAL` | — |
| 10 Reproducibility drill | Execute the rebuild and verification procedures from a clean shell | 04 | `PLANNED` | — |
| 11 Responsive user interface | Usable pages on a phone, and removal of external runtime dependencies | 02 | `CLOSED` | v0.8.0, PR #6–#9 |

Two blocks did not follow the planned order, and that is recorded rather than smoothed over:

- **Block 07 closed before Block 06.** CI delivers value on every subsequent change, and it caught critical vulnerabilities immediately. Backups protect data that, in a demonstration, is disposable. The ordering was a deliberate judgement; the consequence is that the data-loss risk has been open longer.
- **Block 11 was never planned.** The responsive interface was added because the demonstration is viewed in a browser, including on a phone. It also removed every external CDN dependency, which closed a whole class of defect.

## Next block

**Block 06 — Data durability.** It is the only `PLANNED` block that addresses a risk which is both live and irreversible.

| Step | Action | Effort |
|---|---|---|
| 06-A | Patch the existing PersistentVolume reclaim policy to `Retain`, and change the StorageClass so future volumes inherit it | One command, no downtime, reversible |
| 06-B | A scheduled `pg_dump` to S3, using Pod Identity so no credential is stored | — |
| 06-C | A restore script, and a restore actually performed with row counts compared | — |
| 06-D | Retention lifecycle, and a check that the latest backup is recent and non-empty | — |

06-A is independently deliverable and worth doing before anything else:

```bash
PV=$(kubectl -n vote-dev get pvc data-postgres-0 -o jsonpath='{.spec.volumeName}')
kubectl get pv "$PV" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}{"\n"}'   # expect Delete
kubectl patch pv "$PV" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl get pv "$PV" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}{"\n"}'   # expect Retain
```

Editing the StorageClass does **not** change volumes that already exist: the reclaim policy is copied onto the PersistentVolume at provisioning time. Both the existing volume and the class must be changed. Doing only the class is a common and silent mistake.

`Retain` is not a backup. It protects against deleting the claim and nothing else.

### Acceptance criteria for Block 06

| # | Criterion | Verification |
|---|---|---|
| 1 | The existing volume survives deletion of its claim | `kubectl get pv <name> -o jsonpath='{.spec.persistentVolumeReclaimPolicy}'` returns `Retain` |
| 2 | Future volumes inherit the policy | The StorageClass in the cluster and in Git both say `Retain` |
| 3 | The backup job produces a non-empty object | Trigger it, then list the bucket |
| 4 | The job holds no static credential | Service account uses Pod Identity; no AWS key mounted |
| 5 | The bucket is private, versioned and encrypted | Terraform resource plus `aws s3api get-bucket-*` |
| 6 | **The backup can be restored** | Restore into a throwaway target, compare row counts. A backup never restored is not a backup. |
| 7 | **The written procedure works unaided** | A restore performed following only the documentation, with no improvisation |
| 8 | Recovery time is measured | Timed during criterion 6, recorded as a real figure |
| 9 | The data loss window is stated | Derived from the schedule, as an explicit documented acceptance |
| 10 | The demonstration is unaffected | [operations/operate.md](operations/operate.md) section 1 passes |

## Block 04 — what remains

Three of five scope items are delivered. The block stays open for the fourth.

| Item | State | Evidence |
|---|---|---|
| Remove blocked active content | **Done** | v0.4.2 pinned jQuery over HTTPS; v0.8.0 removed every external asset, so the page now loads no third-party resource at all |
| Enforce HTTPS | **Done** | v0.5.0, `e10f1bc`. Verified: `http://…/result/?x=1` returns 301 to the same HTTPS path and query. |
| Repair the defective hygiene test | **Done** | `11b36e6`. Now asserts on real Terraform roots and manifests, and asserts each file exists before checking it is not ignored. |
| Browser verification | **Done** | Operator-verified in Chrome, 15 October 2026; browser version not recorded. Clean console, voted state shown on the POST response, live result updates observed. |
| **Security response headers** | **Not started** | Verified absent: no `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options` or `Referrer-Policy`, and `Server: gunicorn` is disclosed |

### Remaining criteria

| # | Criterion | Verification | Expected |
|---|---|---|---|
| 1 | Security headers present on HTTPS | `curl -sSI https://wtt-demo.syachin.de/` | All four headers present |
| 2 | HSTS is not sent over plain HTTP | `curl -sSI http://wtt-demo.syachin.de/` | No `Strict-Transport-Security` on the redirect response |
| 3 | The server banner is not disclosed | `curl -sSI https://… \| grep -i '^server:'` | Absent or non-identifying |
| 4 | Routing still correct after the change | [operations/operate.md](operations/operate.md) section 1 | All checks pass |

The intended mechanism is a `ResponseHeaderModifier` filter on the routes attached to the `websecure` listener, which keeps HSTS off plaintext responses by construction. It is an Extended-conformance Gateway API feature; confirm Traefik `41.7.1` supports it before planning the work, because the fallback — setting headers in three applications in three languages — is a different block.

```bash
kubectl -n vote-dev describe httproute vote | tail -20
```

## Closed blocks, in brief

Full narrative is in [../CHANGELOG.md](../CHANGELOG.md). These are the acceptance records.

### Block 00 — Repository foundation

Hygiene tests written failing first (`cecfd3c`) then made to pass (`0566c94`), which is visible in the history and is the evidence that the tests can fail. Twelve unit tests. Removed a `.env` symlink into a previous project's secret directory, committed .NET build output containing another developer's paths, and a compose file with plain-text credentials and TLS verification disabled.

One test was defective at closure and asserted on paths from the abandoned layout, so it could not fail. Found during the documentation audit, fixed in Block 07.

### Block 01 — AWS infrastructure

Four Terraform roots applied in order. Nodes in private subnets with no public address. Cluster API restricted by a variable validation that rejects `0.0.0.0/0`. EBS CSI with Pod Identity, proven by PostgreSQL binding a volume in Block 02.

**Outstanding evidence:** an empty `terraform plan` in all three roots has never been recorded. That is the real proof the code describes reality, and it is part of Block 10.

### Block 02 — Kubernetes applications

Five workloads running, operator-confirmed at the time. **PostgreSQL data verified to survive a pod restart** — the one durability property that was actually tested. The full vote path confirmed end to end. No credential value in any manifest; all supplied by `secretKeyRef` or `envFrom`.

**Outstanding evidence:** Gateway and route status, and the Secret's key names, have not been read from the cluster and recorded.

### Block 03 — Public HTTPS

Externally verified on 15 October 2026: DNS resolves to two addresses, the certificate is Let's Encrypt production for the correct name, valid to 12 January 2027, and all routing behaviours are correct.

The block closed believing itself complete, then a browser revealed that `/result` without a trailing slash returned HTTP 200 while the page's JavaScript never loaded. Fixed in `6ea8755`. **That gap is why Block 04 exists and why its criteria require browser-level observation.**

**Outstanding evidence:** in-cluster certificate and Gateway status, and load balancer target health.

### Block 05 — GitOps with Argo CD

Adoption of a live system done conservatively: an isolated `gitops-demo` workload first, then the application Deployments, with manual sync before automatic, and `prune` left off throughout.

| Criterion | Result |
|---|---|
| Argo CD not publicly reachable | `ClusterIP`, no route. Access by port-forward. |
| `AppProject` restricts source, destination and resource kinds | `vote-dev` project allows only `Service` and `apps/Deployment` in `vote-dev` |
| Adoption recreates nothing | The demonstration stayed up; no resource replacement observed |
| Self-heal works | Enabled in `8ac5789` after adoption was verified |
| Rollback by Git revert | **Exercised twice**: demo rolled back v2 to v1 in `b5b413a`; a vote image rolled back in `3f9d2a6` and re-applied in `eac7c13` |
| The manual Secret survives | `prune: false`, and the Secret is in no manifest, so Argo CD never tracks it |
| No destructive test against the public demonstration | None performed. Pruning was never enabled on the application. |

**Deliberate scope limit:** Argo CD manages the application Deployments and Services only. HTTPRoutes, `k8s/base`, cert-manager and Traefik remain manual. Widening the scope is unscheduled future work.

### Block 07 — CI pipeline

Closed ahead of Block 06. Tests for three languages, a dated image version scheme, OCI labels, and a Trivy CRITICAL gate placed **between** build and push so a vulnerable image never reaches the registry.

The gate proved itself immediately: it blocked publication and forced `express` and `StackExchange.Redis` upgrades plus operating-system patching in two Dockerfiles. See version 0.7.1.

Also in this block: branch checks separated from publishing, so a pull request runs tests without producing images, and the Block 00 hygiene test repaired.

**Not included:** image signing, software bill of materials, and a non-blocking scan report in the security tab. Deferred.

### Block 11 — Responsive user interface

Unplanned. Both pages rebuilt to work on a phone, and — more importantly for the platform story — **every external runtime dependency removed**.

| Before | After |
|---|---|
| jQuery, jQuery cookie plugin, Font Awesome from three content delivery networks | No external requests. The vote page uses `url_for('static', …)` and needs no JavaScript at all. |
| Voted state rendered by jQuery after page load | Rendered server-side by Jinja, `{% if vote == 'a' %}selected{% endif %}` |
| Result page assets resolved against the request path | `<base href="./">` plus relative paths |

This closes defects D5a, D5b and D5c by deletion rather than by correction, which is the better outcome. The page is now also immune to a CDN outage.

## Deferred

Recorded so an absence reads as a decision. Defect identifiers refer to [application.md](application.md#defect-register).

| Item | Reason |
|---|---|
| D1 duplicate vote rows, D2 vote lost after a database reconnect | Correctness bugs needing a schema migration and a worker change. Not visible unless a reviewer votes twice and compares totals. |
| D4 worker port configuration, D13 voter identifier slice | Low impact. Cheap to fix alongside Block 09. |
| D6 unpinned Python dependencies, D10 root containers, D15 health and metrics endpoints | Block 09. |
| D12 unused Node dependencies and a duplicate require | Block 09. |
| Image signing, software bill of materials, non-blocking scan reporting | Extends Block 07. |
| Prometheus, Grafana, alerting | Block 08. Real cost; limited value for a short demonstration. No alert exists today, including on certificate renewal failure. |
| Log aggregation | Not planned. `kubectl logs` is sufficient at this scale. |
| `vote-prod` and a promotion process | Needs wider CI and GitOps scope first. Documenting a promotion process now would be fiction. |
| Argo CD managing routing, data services, cert-manager and Traefik | Blast radius. A later block after the current scope is proven. |
| Proxy Protocol v2 | Needs a coordinated change on the Service annotation and the Traefik entrypoint; one side alone breaks all traffic. |
| VPC CNI on a dedicated Pod Identity role | `AmazonEKS_CNI_Policy` sits on the node role, acknowledged in a code comment. Works, not least privilege. |
| Route 53 record moved out of the `iam` root, and the hardcoded load balancer hostname resolved | Needs `external-dns` or an accepted manual step. Changing it risks DNS for the live demonstration. |
| Node right-sizing | Constrained by VPC CNI pod density. Changing the instance type recycles nodes and interrupts the demonstration. |
| Second NAT gateway, second Traefik replica, PodDisruptionBudget | Cost and scope decisions for a demonstration. Traefik is the main single point of failure. |
| `single_nat_gateway` variable that only runs a validation | Cosmetic. |
| `infra/terraform/modules/` empty directory | Cosmetic leftover from the original plan. |

## Superseded plan

The original pre-implementation plan specified 14 blocks, 186 tests, a Helm umbrella chart, External Secrets Operator and an observability stack. It was not followed past its early blocks, and this roadmap replaces it. Its block numbering differs and the two should not be conflated; the mapping is in [decisions/README.md](decisions/README.md).

It remains readable at commit `5898c60`:
[`docs/dev/deployment-plan.md`](https://github.com/asyachin/wtt-demo/blob/5898c60/docs/dev/deployment-plan.md) ·
[`docs/roadmap.md`](https://github.com/asyachin/wtt-demo/blob/5898c60/docs/roadmap.md)
