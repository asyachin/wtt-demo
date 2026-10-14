# WTT CampusONE — Platform Engineering Demonstration

**A technical demonstration prepared for the WTT CampusONE Platform & Systems Engineering Team**

**Linux · Kubernetes · Gateway API · Helm · Terraform · Argo CD · GitHub Actions · Prometheus · Grafana**

## About This Project

This project was created for **WTT CampusONE GmbH** as part of my application for the **Platform & Systems Engineer (m/w/d)** position.

Instead of only describing my experience, I built a working system. It shows how I design infrastructure, automate delivery, run Kubernetes, set up observability, and write technical documentation.

The workload is a small three-tier voting application. The application itself is not the point. The point is the engineering work needed to build, deploy, operate, monitor, secure, and recover it.

**Live demonstration:** https://wtt-demo.syachin.de

## Architecture and Technology Stack

| Area | Technology |
|---|---|
| Operating system | Linux (Ubuntu, Amazon Linux 2023 nodes) |
| Container orchestration | Kubernetes (AWS EKS), Helm |
| Traffic routing | Kubernetes Gateway API, Traefik v3, Network Load Balancer |
| Certificates | cert-manager, Let's Encrypt, DNS-01 through Route 53 |
| Infrastructure as Code | Terraform |
| GitOps delivery | Argo CD |
| CI | GitHub Actions |
| Container registry | GitHub Container Registry (GHCR) |
| Application | Flask web UI, Node.js result UI, .NET background worker |
| Data services | PostgreSQL and Redis, running as containers in the cluster |
| Monitoring | Prometheus, Grafana (read access over HTTP API) |
| Security | TLS, Kubernetes RBAC, network policies, non-root containers, AWS Secrets Manager |

The platform runs on AWS, but the operational patterns apply to a private cloud as well.

## Engineering Focus

### 1. Kubernetes and Linux Operations

Container lifecycle, health checks, resource requests and limits, rolling updates, persistent storage, and systematic troubleshooting.

### 2. Infrastructure Automation and GitOps

Reproducible infrastructure with Terraform, CI with GitHub Actions, and declarative delivery with Argo CD. Git is the single source of truth for both infrastructure and application state.

### 3. Monitoring and Observability

Application and platform metrics in Prometheus, dashboards and alerts in Grafana, and a documented path from an alert to a root cause.

### 4. Data Persistence and Recovery

PostgreSQL and Redis on persistent volumes, scheduled backups to S3, and a restore procedure that is tested, not only written down.

### 5. Security and Operational Ownership

TLS everywhere, least-privilege IAM and RBAC, secrets kept out of Git, image vulnerability scanning, and documented operational responsibilities.

## Live Demonstration

The application lets a visitor submit a **FOR / AGAINST** vote. The vote travels through the full stack: web UI, Redis queue, background worker, PostgreSQL, and a live result page.

| Endpoint | Purpose |
|---|---|
| https://wtt-demo.syachin.de/ | Voting page |
| https://wtt-demo.syachin.de/result | Live result page |
| https://grafana.wtt-demo.syachin.de | Dashboards, and the metrics HTTP API |

Read-only API access for Grafana and Prometheus queries is described in [docs/ops/observability.md](docs/ops/observability.md).

## Documentation

| Topic | Document |
|---|---|
| Project scope and document index | [docs/about.md](docs/about.md) |
| Delivery status per block | [docs/roadmap.md](docs/roadmap.md) |
| Target architecture | [docs/arch/overview.md](docs/arch/overview.md) |
| Application inventory and known defects | [docs/arch/application.md](docs/arch/application.md) |
| Deployment plan | [docs/dev/deployment-plan.md](docs/dev/deployment-plan.md) |
| Architecture decisions | [docs/adr/README.md](docs/adr/README.md) |
| Operations and runbooks | [docs/ops/runbooks.md](docs/ops/runbooks.md) |

## Project Objective

The purpose of this demonstration is to make my engineering approach visible and verifiable: **reliability, automation, maintainability, troubleshooting, and ownership of the full platform lifecycle**.

This is an independent technical demonstration created only for my application to WTT CampusONE. It is not an official WTT CampusONE product, service, or infrastructure.

---

**Developed by:** [Alexander Syachin](https://github.com/asyachin)
**Prepared for:** WTT CampusONE GmbH — Platform & Systems Engineer (m/w/d)
**Demonstration:** https://wtt-demo.syachin.de
**Status:** Work in progress
