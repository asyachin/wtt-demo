# Decision records

Two sets of records, kept deliberately apart.

| Set | What it is | Location |
|---|---|---|
| **0001–0016** | The original pre-implementation design record. Written on 14 October 2026, in a single commit, **before any infrastructure existed**. Preserved byte-for-byte. | [initial/](initial/) |
| **0017–0020** | Decisions actually made during implementation, written down afterwards. Each is explicitly labelled retrospective and names the commits it was reconstructed from. | this directory |

This index is a living document, not a record. It states which original decisions still apply. It does not modify any record, including status fields.

## Why the originals are not edited

[ADR 0001](initial/0001-record-architecture-decisions.md) established that a record is never edited once accepted, only superseded. That rule is honoured literally here, including where implementation went on to contradict a record.

The consequence is that reading `initial/` alone will mislead you about the current system. That is the intended trade: the records show what was believed on 14 October, and this index plus [../reconciliation.md](../reconciliation.md) show what is true now. An edited record would have destroyed the only evidence of what was believed and when.

**Honest provenance.** All sixteen were authored in one sitting during the design phase, in commit `5898c60`. They are an up-front design record, not an organic decision log accumulated over months. Presenting them as the latter would be a false claim.

## Original records: current applicability

| # | Title | Still applies? |
|---|---|---|
| [0001](initial/0001-record-architecture-decisions.md) | Record architecture decisions | **Yes.** The practice is followed, which is why the records below are preserved rather than corrected. |
| [0002](initial/0002-keep-polyglot-application.md) | Keep the application in three languages | **Yes.** No service was rewritten. |
| [0003](initial/0003-single-cluster-two-namespaces.md) | One cluster, two namespaces | **Partly.** One cluster, as decided. Only `vote-dev` is deployed; `vote-prod` is empty and is not a production environment. The private-nodes and single-NAT reasoning holds in full. |
| [0004](initial/0004-data-services-in-cluster.md) | PostgreSQL and Redis in the cluster | **Partly.** The decision holds. Three details differ: the volume is 5 GiB not 10, its reclaim policy is `Delete` not `Retain`, and Redis has no volume at all. The backup the record promised does not exist. |
| [0005](initial/0005-gitops-with-argocd.md) | Deliver with Argo CD | **Deferred.** Not installed. Intent unchanged; see [../blocks/05-gitops.md](../blocks/05-gitops.md). |
| [0006](initial/0006-registry-and-image-tags.md) | GHCR, and a dual-image tag scheme | **Partly.** GHCR, as decided. The tag scheme, the paired dev and prod images, signing and SBOM were all dropped in favour of one image per service tagged with the source commit. |
| [0007](initial/0007-secrets-management.md) | AWS Secrets Manager plus External Secrets Operator | **No.** Superseded by [0020](0020-manual-postgres-secret.md). The record's central principle — no secret in Git — is upheld by different means. |
| [0008](initial/0008-ingress-and-dns.md) | One ALB with ACM | **No.** Superseded during design, before implementation, by 0015 and 0016. The record says so itself. |
| [0009](initial/0009-observability.md) | Prometheus and Grafana with a read-only API | **Deferred.** Nothing installed. `grafana.wtt-demo.syachin.de` does not resolve. Block 08, optional. |
| [0010](initial/0010-no-ansible.md) | Do not use Ansible | **Yes.** No Ansible in the repository. |
| [0011](initial/0011-container-build-standards.md) | Multi-stage, non-root, pinned, labelled images | **Deferred.** `vote` and `worker` are multi-stage; `result` is single-stage and ships `nodemon`. All three run as root. Python dependencies are unpinned. No OCI labels. Block 09. |
| [0012](initial/0012-testing-strategy.md) | One Python test harness, four layers, Trivy non-blocking | **Partly.** The pytest harness and the markers exist. 12 unit tests exist against a planned 186. No integration, platform or end-to-end tests. No CI, so the Trivy reasoning is untested. |
| [0013](initial/0013-branching-and-promotion.md) | Two branches, auto-merge into dev, manual promotion | **Partly.** Block branches and `dev` as the integration branch, as decided. `main` lags at `5898c60`. No CI, so no auto-merge and no promotion. |
| [0014](initial/0014-domain-and-dns-zone.md) | Use `wtt-demo.syachin.de` | **Yes.** One detail differs: the certificate covers a single name, not the wildcard the record describes. |
| [0015](initial/0015-traefik-gateway-api.md) | Traefik with the Gateway API | **Yes**, and it is the most accurate of the sixteen. Two items within it are not done: the HTTP-to-HTTPS redirect and the response security headers, both Block 04. Proxy Protocol v2 is deferred. |
| [0016](initial/0016-tls-with-cert-manager.md) | cert-manager with Let's Encrypt and DNS-01 | **Yes.** Implemented as described, including the staging-first sequence. The least-privilege scoping went further than the record proposed. The wildcard did not happen. |

Summary: 5 apply in full, 6 apply in part, 3 are deferred, 2 are superseded.

## Retrospective records

Each carries a `Recorded` field naming the commits it was reconstructed from. None is given a date earlier than the day it was written.

| # | Title | Reconstructed from |
|---|---|---|
| [0017](0017-terraform-multi-root.md) | Four Terraform roots instead of one | `d586dc5`, `5047e0c` |
| [0018](0018-eks-pod-identity.md) | EKS Pod Identity instead of IRSA | `0967c66`, `71f0e0a` |
| [0019](0019-plain-manifests-not-helm.md) | Plain Kubernetes manifests instead of a Helm chart | `fa8f5e7`, `b940f96`, `50ef706` |
| [0020](0020-manual-postgres-secret.md) | A manually created Secret instead of External Secrets | `b940f96`, `2d1049f` |

## Known limitation of this archive

Every Markdown link inside `initial/` points at a sibling record in the same directory. All eighteen files moved together, so **no link in the archive is broken** — verified by a link check across all 297 internal links in the documentation.

What the records do contain is **seven plain-text path references**, written as inline code rather than links, pointing at planning documents that no longer exist in the working tree:

| Record | Stale reference |
|---|---|
| 0002 | `docs/dev/deployment-plan.md` |
| 0007 | `docs/ops/secrets.md` |
| 0009 | `docs/ops/observability.md` |
| 0010 | `docs/about.md`, three times |
| 0012 | `docs/dev/testing-strategy.md` |

These are **not repaired**, because repairing them would mean editing records that must stay byte-for-byte unchanged. Immutability was judged more valuable than tidy prose inside a historical archive. They are listed here so a reader who follows one and finds nothing knows why.

To read the originals alongside the documents they reference, use the commit where they were written:

- [`docs/adr/` at 5898c60](https://github.com/asyachin/wtt-demo/tree/5898c60/docs/adr)
- [`docs/dev/deployment-plan.md` at 5898c60](https://github.com/asyachin/wtt-demo/blob/5898c60/docs/dev/deployment-plan.md)
- [`docs/arch/overview.md` at 5898c60](https://github.com/asyachin/wtt-demo/blob/5898c60/docs/arch/overview.md)

## Adding a record

Use [initial/template.md](initial/template.md). Next number is 0021.

Write a record when a choice is hard to reverse, costs money, affects security, will surprise a reader, or was contested. Do not write one for something a linter or a test already enforces.

To change a decision: write a new record, reference the old one, and leave the old one untouched.
