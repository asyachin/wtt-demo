# Delivery roadmap

Current baseline: `dev` at commit `a4d979f`, 15 October 2026.

Status vocabulary is defined in [process.md](process.md#status-vocabulary). In short: `CLOSED` means the Definition of Done was satisfied and the work is merged into `dev`.

## Blocks

| Block | Purpose | Depends on | Status | Acceptance evidence |
|---|---|---|---|---|
| [00](blocks/00-repository-foundation.md) Repository Foundation | Repository structure, ignore rules, hygiene tests, working local stack, legacy removal | — | `CLOSED` | Merge `4667c11`. `cecfd3c` RED, `0566c94` GREEN, `2d1049f`. 12 unit tests, one of which is defective (T1). |
| [01](blocks/01-aws-infrastructure.md) AWS Infrastructure | S3 state backend, VPC, NAT, IAM, EKS 1.36, node group, EBS CSI with Pod Identity, `gp3` | 00 | `CLOSED` | Merge `2192eda`. `d586dc5`, `5047e0c`, `fd3c7f5`, `0967c66`. Four Terraform roots applied. |
| [02](blocks/02-kubernetes-applications.md) Kubernetes Applications | Five workloads in `vote-dev`, PostgreSQL on an EBS PVC, Traefik with Gateway API, internal routing, credential handling | 01 | `CLOSED` | Merge `5d29446`. `fa8f5e7`, `f0ea1a0`, `f75d7b7`, `b940f96`, `50ef706`. PostgreSQL restart persistence operator-verified. |
| [03](blocks/03-public-https.md) Public HTTPS | cert-manager with Pod Identity, least-privilege Route 53 DNS-01, staging then production certificate, public NLB, Route 53 alias | 02 | `CLOSED` | `71f0e0a`, plus corrective fix `6ea8755`. Externally verified 15 Oct 2026: production certificate, `/` 200, `/result` 301 to `/result/`. |
| [04](blocks/04-demo-quality-gate.md) Public Demo Quality Gate | Make the browser experience correct, not merely HTTP 200: mixed content, HTTP-to-HTTPS redirect, security headers, repair the defective test | 03 | **`IN PROGRESS`** | Partial. `9a9bb9e` and `a4d979f` deployed the mixed-content source fix. Browser confirmation, redirect, headers and test repair all outstanding. |
| [05](blocks/05-gitops.md) GitOps with Argo CD | Adopt the running `k8s/` resources into Argo CD without disrupting the demonstration, and record the undocumented manual bootstrap | 04 | `PLANNED` | — |
| [06](blocks/06-data-durability.md) Data Durability and Recovery | Protect the PostgreSQL volume from accidental deletion, then build and prove a backup and restore procedure | 02 | `PLANNED` | — |
| 07 CI Pipeline | GitHub Actions: lint, unit tests, image build and push to GHCR with a recorded tag scheme. Replaces manual image builds. | 05 | `PLANNED` | — |
| 08 Observability | Metrics and alerting, scoped to what is genuinely useful at this size | 05 | `OPTIONAL` | — |
| 09 Security Hardening | Pod Security Standards, non-root containers, NetworkPolicy, pinned dependencies, health and metrics endpoints | 04, 07 | `OPTIONAL` | — |
| 10 Reproducibility Drill | Execute [operations/reproduce.md](operations/reproduce.md) and [operations/verify.md](operations/verify.md) from a clean shell, correct what is wrong, record the outcome | 04 | `PLANNED` | — |

A block report file exists for every `CLOSED` block, the block in progress, and the next two planned blocks. Blocks 07 to 10 are described here only; their report files are created when they start, so the repository does not carry reports for work that has no agreed criteria yet.

## Interview scope

The demonstration is live and working. The governing constraint is that nothing in the remaining work may put it at risk.

| Priority | Item | Reason |
|---|---|---|
| 1 | Block 04 | The demonstration is browser-facing. A visible JavaScript failure costs more than any missing feature. |
| 2 | This documentation set | The documentation is itself under review. |
| 3 | Block 06 step 1 | One command protects against irreversible data loss. |
| 4 | Block 10 | Proves the reproduction procedure is real rather than aspirational. |
| 5 | Block 05 | A strong talking point, but it touches live routing and resource ownership. Only with Block 04 closed and time to verify. |

Blocks 07, 08 and 09 are post-interview. Starting them first would risk a working demonstration for capabilities a reviewer cannot see.

## Deferred beyond the interview

Recorded so that an absence reads as a decision rather than an oversight. Defect identifiers refer to [application.md](application.md#defect-register).

| Item | Reason |
|---|---|
| D1 duplicate vote rows, D2 vote lost after a database reconnect | Correctness bugs worth fixing, but both need a schema migration and a worker change. Not visible unless a reviewer votes twice and compares totals. |
| D4 worker port configuration, D12 unused dependencies, D13 voter identifier slice | Low impact. Cheap to fix alongside Block 09. |
| D5b unused `jquery.cookie`, D5c Font Awesome CDN | Not blocked by browsers, so not demonstration-affecting. D5b is a deletion, not a fix. |
| D6 unpinned Python dependencies, D10 root containers, D15 health and metrics endpoints | Block 09. Meaningless to enforce without CI, which is Block 07. |
| Image signing, SBOM, vulnerability scanning | Depend on Block 07. |
| Prometheus, Grafana, alerting | Block 08. Real cost and effort; limited value for a short demonstration. No alert exists today, including on certificate renewal failure. |
| Log aggregation | Not planned. `kubectl logs` is sufficient at this scale. |
| `vote-prod` and a promotion process | Needs Blocks 05 and 07 first. Documenting a promotion process with no CI would be fiction. |
| Traefik and cert-manager under Argo CD | Blast radius during adoption. A later block, after Block 05 is proven. |
| Proxy Protocol v2 for real client addresses | Requires a coordinated change to the NLB `Service` annotation and the Traefik entrypoint. One side alone breaks all traffic. |
| VPC CNI on a dedicated Pod Identity role | `AmazonEKS_CNI_Policy` is on the node role, acknowledged in a code comment. Works, not least privilege. |
| Route 53 record moved out of the `iam` root, and the hardcoded NLB hostname resolved | Needs either `external-dns` or an accepted manual step. Changing it now risks DNS for the live demonstration. |
| `single_nat_gateway` variable that only runs a validation and controls nothing | Cosmetic. |
| Node right-sizing from `t3.large` | Constrained by VPC CNI pod density. Changing instance type recycles nodes and interrupts the demonstration. |
| Toolchain inconsistency: `.python-version` `3.15.0rc3`, ruff target `py314`, `vote` image `python:3.11-slim` | Cosmetic, but it weakens any claim of reproducibility. Cheap to fix in Block 09. |
| Second NAT Gateway | Single NAT is a deliberate cost decision. Egress only; inbound is unaffected. |
| PodDisruptionBudget, second Traefik replica | Single-replica Traefik is the main single point of failure. Accepted for a demonstration. |

## Superseded plan

The original pre-implementation delivery plan specified 14 blocks, 186 tests, a Helm umbrella chart, External Secrets Operator, Argo CD, CI and an observability stack. It was not followed past its early blocks, and the current roadmap replaces it.

It remains readable at commit `5898c60`:

- [`docs/dev/deployment-plan.md` at 5898c60](https://github.com/asyachin/wtt-demo/blob/5898c60/docs/dev/deployment-plan.md)
- [`docs/roadmap.md` at 5898c60](https://github.com/asyachin/wtt-demo/blob/5898c60/docs/roadmap.md)

Its block numbering differs from the current scheme and the two should not be conflated. The mapping, and every deviation, is in [reconciliation.md](reconciliation.md).
