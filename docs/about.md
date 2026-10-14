# About This Documentation

## Purpose

This repository deploys a small voting application to AWS EKS and keeps it running. The documentation explains **what** is deployed, **why** it is built that way, and **how** to operate it.

The goal is not a large platform. The goal is a small platform that is simple, efficient, reliable, and reproducible, and that is documented well enough for a second engineer to take it over.

## Language Rule

All documentation, all Architecture Decision Records, and everything inside the application (code comments, log messages, UI text, commit messages) is written in **plain English**. Short sentences. No jargon where a plain word works. This rule has no exceptions.

## Scope

In scope:

- One AWS account, region `eu-north-1`.
- One EKS cluster with two namespaces: `vote-dev` and `vote-prod`.
- The voting application: `vote` (Flask), `result` (Node.js), `worker` (.NET 8).
- PostgreSQL and Redis as containers in the cluster, on persistent volumes.
- Terraform for infrastructure, Helm for packaging, Argo CD for delivery.
- Traffic routing with the Kubernetes Gateway API, implemented by Traefik v3.
- Certificates from Let's Encrypt, issued by cert-manager with a DNS-01 challenge.
- GitHub Actions for build, test, and image publishing to GHCR.
- Prometheus and Grafana for metrics, with read access over HTTP API.
- Public HTTPS on `wtt-demo.syachin.de`.

Out of scope, with reasons:

| Not included | Reason |
|---|---|
| Ansible | Terraform provisions the infrastructure and Helm plus Argo CD manage the workloads. There is no configuration gap left for Ansible. See [ADR 0010](adr/0010-no-ansible.md). |
| AWS RDS and ElastiCache | Managed data services add cost and remove the chance to show StatefulSet, PersistentVolume, and backup/restore work. See [ADR 0004](adr/0004-data-services-in-cluster.md). |
| Multi-region or multi-cluster | One cluster is enough to demonstrate the practices. Cost and operational effort would double. See [ADR 0003](adr/0003-single-cluster-two-namespaces.md). |
| Rewriting the application in one language | The application is the workload, not the deliverable. See [ADR 0002](adr/0002-keep-polyglot-application.md). |
| Centralized log aggregation (Loki) | Optional stretch goal in Block 13. Metrics and alerts come first. |

## Document Index

### Architecture

| Document | Content |
|---|---|
| [arch/overview.md](arch/overview.md) | Target architecture, AWS layout, traffic path, environments |
| [arch/application.md](arch/application.md) | The application as it exists today, its interfaces, and its known defects |

### Development

| Document | Content |
|---|---|
| [dev/deployment-plan.md](dev/deployment-plan.md) | The delivery plan, split into 14 blocks, each with its own tests |
| [dev/git-workflow.md](dev/git-workflow.md) | Branches, commits, the RED/GREEN cycle, auto-merge, promotion |
| [dev/testing-strategy.md](dev/testing-strategy.md) | Test layers, tools, markers, and what each layer is allowed to assume |
| [dev/images-and-tags.md](dev/images-and-tags.md) | Multi-stage builds, the tag scheme, and how a dev image maps to a prod image |
| [dev/local-development.md](dev/local-development.md) | How to run and test the whole stack on a laptop |

### Operations

| Document | Content |
|---|---|
| [ops/secrets.md](ops/secrets.md) | Where every secret lives and how it reaches a pod |
| [ops/observability.md](ops/observability.md) | Metrics, dashboards, alerts, and read-only API access |
| [ops/runbooks.md](ops/runbooks.md) | Step-by-step procedures for normal and abnormal operations |

### Decisions

| Document | Content |
|---|---|
| [adr/README.md](adr/README.md) | Index of all Architecture Decision Records |

## Repository Layout

The target layout. Directories appear as the blocks in the deployment plan are completed.

```
.
├── .github/
│   └── workflows/              CI and image publishing
├── app/
│   ├── vote/                   Flask voting UI
│   ├── result/                 Node.js result UI
│   ├── worker/                 .NET background worker
│   └── docker-compose.yml      Local stack for development and integration tests
├── deploy/
│   ├── helm/wtt-vote/          One umbrella chart for the application
│   └── argocd/                 Argo CD projects and applications
├── infra/
│   └── terraform/
│       ├── modules/            Reusable modules (network, eks, platform, dns)
│       └── env/platform/       The root module that builds the cluster
├── tests/
│   ├── unit/                   No network, no containers
│   ├── integration/            Against the local Docker Compose stack
│   ├── e2e/                    Against a deployed environment over HTTPS
│   └── platform/               Against AWS and the Kubernetes API
└── docs/
```

## Conventions

- Headings use `#` to `###` only. Deeper nesting means the document should be split.
- Tables use the compact form `|---|---|`.
- No emoji anywhere.
- Every ADR has a number, a status, a context, a decision, and consequences.
- Every runbook starts with when to use it and how to confirm the problem is fixed.
- File and command references use backticks. Code references use `path:line`.
