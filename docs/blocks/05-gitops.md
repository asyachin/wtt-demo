# Block 05 — GitOps with Argo CD

| Field | Value |
|---|---|
| Status | `PLANNED` |
| Branch | `block/05-gitops` |
| Depends on | Block 04 `CLOSED` |
| Next | Block 06 |
| Report type | Written before implementation |

## Goal

Make Git the mechanism that applies `k8s/` to the cluster, adopting resources that are **already running and serving public traffic**, with no interruption and no resource recreation.

A second outcome matters as much: the Gateway API CRDs, Traefik and cert-manager were installed by hand and their versions exist only in shell history. The cluster cannot currently be rebuilt from Git alone. This block records them.

## Governing constraint

The demonstration is live and working. Adoption of running resources is the single most dangerous operation in this roadmap, because a careless Argo CD configuration can delete a StatefulSet, drop a Secret, or recreate the Traefik Service and silently break DNS.

Every decision below is therefore biased toward **inspection before action**:

- Manual synchronisation first. Never automated on the first pass.
- Diffs read and understood before anything is adopted.
- **Automatic pruning is not enabled as part of adoption**, and is tested only against an isolated, non-critical resource afterwards.
- Self-healing enabled only after ownership and expected state are confirmed.
- No acceptance test deliberately breaks the live demonstration.

## Scope

| ID | Item |
|---|---|
| 05-A | Install Argo CD by Helm, internally only, with chart version, values and the exact command committed to `k8s/platform/argocd/` |
| 05-B | Record the existing manual bootstrap: Gateway API CRD version, Traefik chart `41.7.1` and its values, cert-manager chart version, in [../operations/reproduce.md](../operations/reproduce.md) |
| 05-C | An `AppProject` restricting source repository, destination namespaces and resource kinds |
| 05-D | One `Application` per path, each with `syncPolicy` manual at creation |
| 05-E | Staged adoption: inspect, then sync manually, then enable self-healing |
| 05-F | Document precisely which resources Argo CD owns and which remain externally managed |
| 05-G | A low-risk GitOps proof using an isolated ConfigMap, with a documented Git revert |

## Out of scope

| Item | Reason |
|---|---|
| Moving the Traefik or cert-manager Helm releases under Argo CD | Blast radius. Recreating the Traefik Service would issue a new NLB and break the hardcoded Route 53 alias. A later block, after this one is proven. |
| Automatic image updates | Block 07. Needs CI first. |
| A second environment or a promotion process | `vote-prod` stays empty. Needs Block 07. |
| Public exposure of the Argo CD interface | Deliberate. Access by `kubectl port-forward` only. |
| Enabling `prune: true` on the application or platform Applications | Explicitly excluded. See 05-G. |

## Prerequisites

- Block 04 `CLOSED`, so the demonstration is in a known-good state before anything is adopted.
- Chart versions and CRD versions for Traefik, cert-manager and the Gateway API, read from the cluster:

```bash
helm list -A
kubectl get crd gateways.gateway.networking.k8s.io \
  -o jsonpath='{.metadata.annotations.gateway\.networking\.k8s\.io/bundle-version}{"\n"}'
```

- A recorded inventory of every resource that will be adopted, captured **before** any Argo CD object is created:

```bash
mkdir -p /tmp/pre-adoption
for ns in vote-dev traefik; do
  kubectl -n $ns get all,pvc,secret,httproute -o yaml > /tmp/pre-adoption/$ns.yaml
done
kubectl -n vote-dev get all,pvc,httproute \
  -o custom-columns='KIND:.kind,NAME:.metadata.name,UID:.metadata.uid' > /tmp/pre-adoption/uids.txt
```

The UID list is the instrument for criterion 2. A changed UID means a resource was deleted and recreated rather than adopted.

**This inventory is not a rollback strategy.** It is a comparison baseline. A YAML dump cannot restore a deleted PersistentVolume, cannot recover data, and does not capture the EBS volume behind the PVC. Real protection for the database is [Block 06](06-data-durability.md), and the honest position is that Block 06 should be done first if there is time.

## Planned work

### 05-A Install Argo CD

Helm, pinned chart version, into namespace `argocd`. `server.service.type` left as `ClusterIP`; no `Ingress`, no `HTTPRoute`, no `LoadBalancer`. The values file and the literal install command are committed, which is the practice that 05-B exists to retrofit for the three components that were installed without it.

Initial admin password retrieval, and the port-forward access path, documented in [../operations/troubleshoot.md](../operations/troubleshoot.md) without recording any password value.

### 05-C Restrict the project

An `AppProject` named `wtt-demo` that permits:

- source: this repository only,
- destinations: namespaces `vote-dev` and `traefik` only,
- cluster-scoped resources: `Namespace` and `StorageClass` only, since `k8s/base` contains both.

Everything else denied. An `Application` that names `kube-system` is then rejected by the project rather than by luck.

### 05-D Applications, manual sync

| Application | Path | Namespace | Notes |
|---|---|---|---|
| `wtt-base` | `k8s/base` | `vote-dev` | Namespaces, StorageClass, PostgreSQL, Redis. Contains cluster-scoped objects. |
| `wtt-apps-dev` | `k8s/apps/dev` | `vote-dev` | Deployments, Services, HTTPRoutes |
| `wtt-cert-manager-config` | `k8s/platform/cert-manager` | `traefik` | ClusterIssuers and Certificates, **not** the cert-manager installation |

All three created with `syncPolicy` absent, meaning manual. `targetRevision: dev`, matching the working branch. `prune` is not set anywhere.

`k8s/platform/traefik/` is **not** an Application. It is a Helm values file, not a manifest directory, and the release stays under Helm.

### 05-E Staged adoption

| Stage | Action | Gate before proceeding |
|---|---|---|
| 1 | Create the `AppProject` and the three Applications, manual sync | All three report a status; none has synced |
| 2 | `argocd app diff` each one, read every line | Understood. Where Git and the cluster differ, **Git is corrected to match the cluster**, never the reverse. The cluster is serving traffic and is the current truth. |
| 3 | Re-run diffs until empty | Empty diff on all three |
| 4 | `argocd app sync` manually, one at a time | Each reports `Synced` and `Healthy`; UIDs unchanged; no pod restarts; section 1 of verify.md passes |
| 5 | Enable `selfHeal: true`, still no prune | Criterion 7 passes |
| 6 | 05-G prune proof on an isolated ConfigMap only | Criterion 9 passes |

Stage 2 is where the real work is. A non-empty diff on a live resource usually means a field was set by an admission controller, a defaulting webhook, or by hand — and the correct response is to bring Git up to date, not to push Git's version into a running system.

### 05-F Ownership

The outcome is an explicit table, extending the one in [../architecture.md](../architecture.md#ownership-boundaries), naming for every resource whether it is owned by Terraform, Argo CD, Helm, or a manual operator action.

The `postgres-credentials` Secret stays manual. It appears in no manifest, so Argo CD never tracks it. Because Argo CD only prunes resources carrying its tracking label, an untracked Secret is not a prune candidate. That is the reasoning; criterion 8 verifies it rather than trusting it.

### 05-G Prove GitOps without endangering the demonstration

Three low-risk proofs:

| Proof | Method | Risk |
|---|---|---|
| Self-healing | Add a harmless annotation to a live Deployment with `kubectl annotate`, then confirm Argo CD removes it | None. An annotation change triggers no pod restart. |
| Git revert as the rollback path | Commit a benign change — an annotation or a label in Git — sync, then `git revert` and sync again | None |
| Pruning | Add a standalone ConfigMap `gitops-prune-canary` to `k8s/apps/dev`, sync, remove it from Git, sync, confirm it is gone. Prune enabled for that test and then reconsidered. | None. The ConfigMap is referenced by nothing. |

**Explicitly excluded from this block**, on instruction and on merit:

- Deploying a nonexistent image tag to the live `vote` Deployment to demonstrate rollback. It would induce `ImagePullBackOff` on the public demonstration.
- Deleting a critical workload to demonstrate pruning.
- Scaling a Deployment to prove self-healing, when an annotation proves the same reconciliation loop with no pod churn.

The self-healing proof is the one that matters, and an annotation demonstrates it exactly as well as a replica change.

## Acceptance criteria

| # | Criterion | Verification | Expected |
|---|---|---|---|
| 1 | Argo CD installation is reproducible from Git | The committed values file and install command in `k8s/platform/argocd/` | A reader can install the same chart version without guessing |
| 2 | **Adoption recreates nothing** | Compare `metadata.uid` for every adopted resource against `/tmp/pre-adoption/uids.txt` | Every UID unchanged. A changed `postgres-0` UID would mean the StatefulSet was recreated. |
| 3 | Git matches the cluster before any sync | `argocd app diff` on all three | Empty. Divergence resolved by correcting Git. |
| 4 | No pod restarts or restarts-count changes during adoption | `kubectl -n vote-dev get pods` before and after, comparing `RESTARTS` and `AGE` | Restart counts unchanged, ages continuous |
| 5 | The demonstration stays up at every stage | [../operations/verify.md](../operations/verify.md) section 1 after each stage | All checks pass every time |
| 6 | Applications healthy | `argocd app list -o wide` | All `Synced` and `Healthy` |
| 7 | **Self-healing works** | `kubectl -n vote-dev annotate deploy/vote drift-test=true --overwrite`, wait one sync interval, re-read | The annotation is removed. No pod restart. **This is the criterion that proves GitOps is real rather than decorative.** |
| 8 | **The manual Secret survives** | After adoption and after each sync: `kubectl -n vote-dev get secret postgres-credentials` and check for an Argo CD tracking label | The Secret exists and is untracked. Verified at every stage, never assumed. |
| 9 | Pruning works, in isolation | The `gitops-prune-canary` ConfigMap sequence in 05-G | The ConfigMap disappears; nothing else changes |
| 10 | Git revert is a working rollback path | Revert the benign change from 05-G and sync | The cluster returns to the previous state with no manual `kubectl`, no downtime, no data loss |
| 11 | The `AppProject` restricts scope | Attempt an `Application` targeting `kube-system` | Rejected by the project |
| 12 | Argo CD is not publicly reachable | `kubectl -n argocd get svc`, and `dig argocd.wtt-demo.syachin.de` | No `LoadBalancer`, no public DNS record. Access by port-forward. |
| 13 | No secret added to Git | Review the branch diff, and a credential scan | Clean. The Argo CD admin password is never committed. |
| 14 | The manual bootstrap is recorded | [../operations/reproduce.md](../operations/reproduce.md) names the Gateway API CRD version, Traefik chart version and cert-manager chart version | All three present, matching what `helm list -A` reports |
| 15 | Ownership documented | 05-F table | Every resource in `k8s/` and every platform component has a named owner |

## Risks and limitations

| Risk | Mitigation |
|---|---|
| Adoption recreates the PostgreSQL StatefulSet, destroying the volume | Criterion 2 UID comparison, manual sync, empty diff before any sync. **Residual risk remains until [Block 06](06-data-durability.md) provides a backup.** |
| A wrong `path` plus pruning deletes live workloads | Pruning not enabled during adoption. Only tested against an unreferenced ConfigMap. |
| Argo CD reverts a manual fix during an incident | Known consequence of `selfHeal`. Incident procedure: change Git, or temporarily disable self-healing. Recorded in [../operations/troubleshoot.md](../operations/troubleshoot.md). |
| Adopting the Traefik Service would issue a new NLB and break the hardcoded Route 53 alias | Out of scope. Traefik stays under Helm. |
| `targetRevision: dev` means any commit to `dev` reaches the cluster | Accepted for a single-engineer project. A protected branch and CI would be the control, and that is Block 07. |

Even when closed: no CI, so nothing validates a manifest before Argo CD applies it. The gap between committing a broken manifest and the cluster attempting it is one sync interval.

## Definition of Done

- [ ] Criteria 1 to 15 verified, each with its command and real output recorded
- [ ] Pre-adoption UID inventory captured and compared
- [ ] Public demonstration verified unaffected at every stage
- [ ] `postgres-credentials` confirmed present and untracked after every sync
- [ ] Pruning tested only against the isolated canary ConfigMap
- [ ] No destructive test performed against the live demonstration
- [ ] Manual bootstrap versions recorded in `operations/reproduce.md`
- [ ] Ownership table complete
- [ ] No secret added to the repository
- [ ] Documentation updated per [../process.md](../process.md#documentation-update-at-block-closure)
- [ ] Branch merged into `dev`
- [ ] Status set to `CLOSED` here and in [../roadmap.md](../roadmap.md)
