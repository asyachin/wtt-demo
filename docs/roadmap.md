# Roadmap and Delivery Status

This is the status board. The full description of every block is in [dev/deployment-plan.md](dev/deployment-plan.md).

Update the status column at the end of each block, in the same pull request that closes the block.

## Status Values

| Value | Meaning |
|---|---|
| `todo` | Not started |
| `red` | Tests are written and failing on purpose, pushed to GitHub |
| `green` | Tests pass, branch merged into `dev` |
| `done` | Merged into `main`, running in `vote-prod`, documentation updated |

## Blocks

| # | Block | Branch | Status | Closes |
|---|---|---|---|---|
| 00 | Repository bootstrap and hygiene | `block/00-bootstrap` | todo | Git repo, ignore files, removal of the stale secret symlink |
| 01 | Legacy cleanup and multi-stage images | `block/01-images` | todo | No old project traces, three small non-root images |
| 02 | Health, metrics, and application defects | `block/02-app-contract` | todo | Probes, `/metrics`, no secrets in logs, correct vote counting |
| 03 | Test harness and CI pipeline | `block/03-ci` | todo | Static checks, unit tests, integration tests, Trivy scan |
| 04 | Image publishing and auto-merge | `block/04-publish` | todo | Dev and prod images in GHCR with one shared tag |
| 05 | Helm chart | `block/05-helm` | todo | One chart, two value files, routing validated in `kind` |
| 06 | Terraform: network and EKS | `block/06-eks` | todo | VPC, EKS cluster, node group, remote state |
| 07 | Terraform: platform add-ons | `block/07-addons` | todo | Gateway API CRDs, Traefik and the platform Gateway, cert-manager, ExternalDNS, External Secrets |
| 08 | Argo CD and GitOps bootstrap | `block/08-argocd` | todo | Argo CD, app-of-apps, both namespaces synced |
| 09 | Secrets management | `block/09-secrets` | todo | AWS Secrets Manager plus External Secrets, no secrets in Git |
| 10 | Observability | `block/10-observability` | todo | Prometheus, Grafana, dashboards, alerts, read-only API |
| 11 | Data persistence and recovery | `block/11-data` | todo | Persistent volumes, nightly backup to S3, tested restore |
| 12 | Security hardening | `block/12-hardening` | todo | Network policies, Pod Security, RBAC, resource quotas |
| 13 | Final documentation and demo readiness | `block/13-release` | todo | Runbooks complete, disaster recovery drill recorded, demo script |

## Current Known Blockers

| Item | Impact | Resolved in |
|---|---|---|
| `app/.env` is a symlink to the previous project's secret file. Docker Compose loads it automatically and it silently overrides the intended environment. | Wrong credentials and wrong endpoints during local runs | Block 00 |
| `app/.env.dev` starts with a bare line `eu-north-1` that is not a `KEY=VALUE` pair. | `docker compose --env-file` and `source` both fail or warn | Block 00 |
| `app/worker/obj/` is committed and contains another developer's absolute paths and an old commit hash. The ignore rules are now in place, so the directory only has to be deleted. | Leaks unrelated history, breaks reproducible builds | Block 00, deletion. Block 01, the rest. |
| The voting page loads jQuery over plain `http://` from a CDN. | The browser blocks it on an HTTPS site, so the "you voted" behaviour breaks in production | Block 02 |
| The `votes` table has no primary key, so a second vote from the same visitor adds a row instead of replacing it. | Vote counts are wrong | Block 02 |
| The worker ignores `DB_PORT` and `REDIS_PORT` and prints the database password to stdout. | Not configurable, and the password ends up in logs | Block 02 |
| The result service prints its PostgreSQL connection string, including the password, at startup. | Password in logs | Block 02 |
| `infra/` is empty and `app/.env.template` tells the reader to run `terraform apply` in a directory that does not exist. | Documentation does not match reality | Block 06 |

## Cost Expectation

Rough monthly cost for the demonstration environment in `eu-north-1`, while it is running.

| Item | Estimate |
|---|---|
| EKS control plane | 72 USD |
| 2 x `t3.small` nodes, Spot | 10 USD |
| 1 NAT gateway | 35 USD |
| 1 Network Load Balancer | 18 USD |
| EBS volumes, 40 GiB gp3 | 4 USD |
| S3 backups, Route 53, data transfer | 3 USD |
| Certificates, Let's Encrypt | 0 USD |
| **Total** | **about 142 USD per month** |

The teardown procedure is in [ops/runbooks.md](ops/runbooks.md). Run it when the interview process ends.
