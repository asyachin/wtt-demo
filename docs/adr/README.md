# Architecture Decision Records

An Architecture Decision Record captures one decision, the situation that forced it, and what it costs. It is written when the decision is made, not afterwards.

A record is never edited once it is accepted. If a decision changes, a new record supersedes the old one, and the old one stays in place with its status changed. The history of what was believed and why is part of the value.

The process itself is described in [0001-record-architecture-decisions.md](0001-record-architecture-decisions.md).

## Index

| # | Title | Status | Decided in |
|---|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | Block 00 |
| [0002](0002-keep-polyglot-application.md) | Keep the application as it is, in three languages | Accepted | Block 00 |
| [0003](0003-single-cluster-two-namespaces.md) | One EKS cluster with two namespaces | Accepted | Block 00 |
| [0004](0004-data-services-in-cluster.md) | Run PostgreSQL and Redis in the cluster | Accepted | Block 00 |
| [0005](0005-gitops-with-argocd.md) | Deliver with Argo CD, and draw the Terraform boundary | Accepted | Block 00 |
| [0006](0006-registry-and-image-tags.md) | Use GHCR, and tag two images with one identifier | Accepted | Block 00 |
| [0007](0007-secrets-management.md) | Two secret stores, with a sharp boundary | Accepted | Block 00 |
| [0008](0008-ingress-and-dns.md) | One ALB, ACM, and ExternalDNS | Superseded by 0015 and 0016 | Block 00 |
| [0009](0009-observability.md) | Publish Grafana only, and reach Prometheus through it | Accepted | Block 00 |
| [0010](0010-no-ansible.md) | Do not use Ansible | Accepted | Block 00 |
| [0011](0011-container-build-standards.md) | Multi-stage builds, non-root, pinned, labelled | Accepted | Block 00 |
| [0012](0012-testing-strategy.md) | One Python test harness, and Trivy does not block | Accepted | Block 00 |
| [0013](0013-branching-and-promotion.md) | Two branches, auto-merge into dev, manual promotion | Accepted | Block 00 |
| [0014](0014-domain-and-dns-zone.md) | Use wtt-demo.syachin.de | Accepted | Block 00 |
| [0015](0015-traefik-gateway-api.md) | Route with Traefik and the Gateway API | Accepted | Block 00 |
| [0016](0016-tls-with-cert-manager.md) | Terminate TLS in the cluster, with cert-manager and Let's Encrypt | Accepted | Block 00 |

## Status Values

| Status | Meaning |
|---|---|
| `Proposed` | Written, not yet agreed. No record should stay here once work starts. |
| `Accepted` | In force. The implementation follows it. |
| `Superseded by NNNN` | Replaced. Kept for the history. |
| `Rejected` | Considered and declined. Kept so the option is not reopened without new information. |

`test_every_adr_has_a_status` in Block 13 checks that no record is still `Proposed` at release.

## When to Write One

Write a record when a choice:

- is hard to reverse, such as a domain name, a region, or a state backend;
- costs money, such as a managed service or a second cluster;
- affects security, such as where a secret lives or what an IAM role can do;
- will surprise a reader, such as a scanner that does not block a build;
- was contested, so that the rejected option and its reason are preserved.

Do not write a record for something a linter or a test already enforces. A naming convention belongs in a lint rule, not in a decision record.

## How to Add One

1. Copy [template.md](template.md) to `NNNN-short-kebab-title.md`, using the next free number.
2. Fill it in. Keep it to one page. A record longer than a page is usually two decisions.
3. Add a row to the index above.
4. Commit it in the same pull request as the work it governs. A record written a week later is a rationalisation, not a decision.

To change an existing decision: write a new record, reference the old one, and set the old one to `Superseded by NNNN`.
