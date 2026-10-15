# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Because this is a demonstration platform rather than a published library, a minor version marks a completed delivery block or a user-visible change, and a patch version marks a fix or a security update.

**Note on tags.** The git tags `v0.1.0` through `v0.8.0` were created on 2026-10-15, during the documentation reconciliation, and applied to commits that already existed. The commits and their dates are unchanged. No release date below is claimed to be the date its tag was created.

Every version links to the merge commit or pull request that delivered it. Delivery blocks are described in [docs/roadmap.md](docs/roadmap.md).

## [Unreleased]

### Added
- Consolidated documentation set: architecture, roadmap, process, operations and decisions, replacing the pre-implementation plan.
- This changelog, and retroactive version tags for the existing history.

### Fixed
- The PersistentVolume behind `data-postgres-0` was patched live to `reclaimPolicy: Retain`, 15 October 2026, so a claim deletion no longer destroys the volume. Applied directly with `kubectl patch`, **not yet committed**: `k8s/base/storage/gp3.yaml` still declares `reclaimPolicy: Delete`, so a future volume would not inherit the fix. Block 06, step 06-A, half done.

### Known gaps
- Browser security headers are not set on either page, and `vote` discloses `server: gunicorn` while `result` discloses `x-powered-by: Express`. Block 04.
- No PostgreSQL backup. The committed reclaim policy is still `Delete`; only the running volume has been protected by hand. Block 06.
- Argo CD manages only the application Deployments and Services. Routing, data services, cert-manager and Traefik remain manual.

## [0.8.0] — 2026-10-15

Responsive front end for both pages, and the removal of every external runtime dependency.

### Added
- Responsive "cats or dogs" landing page for the vote service, with a local image asset. PR [#6](https://github.com/asyachin/wtt-demo/pull/6), commit `a8703d3`.
- Responsive live results page for the result service. PR [#8](https://github.com/asyachin/wtt-demo/pull/8), commit `ff6abb4`.

### Changed
- The vote page no longer loads jQuery, the jQuery cookie plugin or Font Awesome from a content delivery network. The voted state is now rendered server-side with Jinja, so the page needs no JavaScript at all.
- The result page serves its stylesheet and scripts from relative paths under a `<base href="./">` element.

### Fixed
- Removed the last external asset references, which closes the mixed-content class of defect entirely rather than only correcting one URL. See defects D5, D5a, D5b and D5c in [docs/application.md](docs/application.md).

### Released
- `vote:2026.10.15-1558-build.21-a1-5ccdb9a`, PR [#7](https://github.com/asyachin/wtt-demo/pull/7)
- `result:2026.10.15-1626-build.27-a1-8968dc4`, PR [#9](https://github.com/asyachin/wtt-demo/pull/9)

## [0.7.1] — 2026-10-15

Security update, driven by the Trivy gate added in 0.7.0 failing the build.

### Fixed
- Critical vulnerabilities in the result and worker images. `express` raised from `^4.18.2` to `^4.22.3`, `StackExchange.Redis` from `2.6.66` to `2.13.17`, and `apt-get upgrade` added to both Dockerfiles so operating system packages are patched at build time. PR [#2](https://github.com/asyachin/wtt-demo/pull/2), commit `8625709`.

### Released
- `result:…-build.8`, PR [#3](https://github.com/asyachin/wtt-demo/pull/3)
- `worker:…-build.8`, PR [#4](https://github.com/asyachin/wtt-demo/pull/4)
- `vote:…-build.8`, PR [#5](https://github.com/asyachin/wtt-demo/pull/5)

The pipeline refused to publish until these were fixed, which is the gate working as intended.

## [0.7.0] — 2026-10-15

Continuous integration. Closes delivery Block 07, out of planned order.

### Added
- GitHub Actions workflow `.github/workflows/ci-images.yml`: Ruff lint and pytest for Python, `node --check` and `npm ci` for Node.js, `dotnet build` for .NET. Commit `11b36e6`.
- Image versioning scheme `YYYY.MM.DD-HHMM-build.<run>-a<attempt>-<short sha>`, plus a second tag carrying the full commit SHA. See [ADR 0021](docs/decisions/0021-ci-image-versioning.md).
- Trivy scan on every image, `severity: CRITICAL`, `ignore-unfixed: true`, `exit-code: 1`. An image is built and scanned **before** it is pushed, so a vulnerable image never reaches the registry.
- OCI image labels for version, revision and source.
- Branch checks separated from publishing: tests run on every push and pull request, publishing happens only on a push to `dev`. PR [#1](https://github.com/asyachin/wtt-demo/pull/1), commit `5e7d360`.

### Changed
- The vote image base moved from `python:3.11-slim` to `python:3.14.8-slim-trixie`, commit `11b36e6`.
- Images are now built by CI rather than by hand.

### Fixed
- `tests/unit/test_repository_hygiene.py::test_infrastructure_code_is_not_ignored` asserted on four paths that did not exist, left over from the abandoned single-root layout, so it passed without checking anything. It now asserts on the real Terraform roots and Kubernetes manifests, and asserts that each file exists before checking that it is not ignored. Commit `11b36e6`.

## [0.6.0] — 2026-10-15

GitOps delivery with Argo CD. Closes delivery Block 05.

### Added
- Argo CD installed by Helm, `ClusterIP` only, with no public route. Values in `k8s/platform/argocd/values.yaml`, commit `24086d9`.
- An isolated `gitops-demo` application used to prove the mechanism safely, away from the public demonstration. Commit `24086d9`.
- `AppProject` objects restricting the source repository, the destination namespaces and the permitted resource kinds.
- `vote-dev-apps` Application, tracking `dev`, path `k8s/apps/dev`, adopting the running Deployments and Services without recreating them. Commit `8b0cd57`.

### Changed
- Automatic sync with `selfHeal: true` enabled after adoption was verified, first on the demo application in `fc8a902` and then on the vote application in `8ac5789`.
- `prune` is deliberately left `false`. Argo CD will not delete resources, which keeps the manually created `postgres-credentials` Secret and the hand-applied data services safe.

### Verified
- Rollback by Git revert, exercised twice: the demo application rolled back from v2 to v1 in `b5b413a`, and a vote image rolled back and then re-applied in `3f9d2a6` and `eac7c13`.

### Scope
Argo CD manages only `k8s/apps/dev/applications.yaml`, which holds the three application Deployments and Services. The `AppProject` whitelist permits nothing else. HTTPRoutes, namespaces, storage, PostgreSQL, Redis, cert-manager and Traefik are still applied by hand.

## [0.5.0] — 2026-10-15

HTTPS enforced at the edge. Partially closes delivery Block 04.

### Added
- `HTTPRoute` `http-to-https`, attached only to the Traefik `web` listener, issuing a 301 to HTTPS with the path and query preserved. Commit `e10f1bc`.

### Changed
- The `vote`, `result` and `result-redirect` routes were detached from the `web` listener and now attach to `websecure` only. Plain HTTP is therefore no longer served for any path.

### Not included
Browser security headers. `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options` and `Referrer-Policy` are still absent, and the `Server: gunicorn` banner is still disclosed. Block 04 remains open for that reason.

## [0.4.2] — 2026-10-15

### Fixed
- The vote page loaded jQuery over plain `http://` while being served over HTTPS, so browsers blocked it as mixed active content and the voted-state highlight never worked. The reference was pinned to `https://code.jquery.com/jquery-3.7.1.min.js`. Commits `9a9bb9e` and `a4d979f`. Superseded in 0.8.0, which removed the dependency altogether.

## [0.4.1] — 2026-10-15

### Fixed
- A request to `/result` without a trailing slash returned HTTP 200, but the browser resolved the page's relative asset paths against `/`, so the JavaScript never loaded and the results page stayed empty. Added an `HTTPRoute` with an exact match on `/result` and a 301 redirect to `/result/`. Commit `6ea8755`.

This defect is the reason acceptance criteria in this project now require browser-level verification and not only a status code.

## [0.4.0] — 2026-10-14

Public HTTPS. Closes delivery Block 03. Commit `71f0e0a`.

### Added
- cert-manager with an EKS Pod Identity association, and an IAM policy scoped by three condition keys to `TXT` changes on exactly `_acme-challenge.wtt-demo.syachin.de` in one hosted zone.
- Staging and production `ClusterIssuer` objects, used in that order so a misconfigured solver could not exhaust the Let's Encrypt production quota.
- A public AWS Network Load Balancer, created by switching the Traefik Service to `type: LoadBalancer`.
- A Route 53 A alias record pointing at the load balancer.

## [0.3.0] — 2026-10-14

Kubernetes applications and internal routing. Closes delivery Block 02. Merge commit `5d29446`.

### Added
- PostgreSQL as a StatefulSet on a 5 GiB encrypted `gp3` volume, and Redis as an in-memory queue. Commit `fa8f5e7`.
- The `vote`, `result` and `worker` Deployments and Services, with credentials supplied from a Kubernetes Secret created outside Git. Commit `b940f96`.
- Traefik with the Gateway API provider, a `GatewayClass`, a `Gateway` with `web` and `websecure` listeners, and the application routes. Commit `50ef706`.
- A rotation script for the PostgreSQL password, `scripts/rotate_k8s_postgres_password.py`.

### Changed
- The result service runtime moved to Node.js 22. Commit `f0ea1a0`.

### Fixed
- The worker printed its full PostgreSQL connection string, including the password, to standard output. Commit `f75d7b7`.

### Verified
- PostgreSQL data survives a pod restart: the volume detaches and reattaches to the rescheduled pod. Operator-verified.

## [0.2.0] — 2026-10-14

AWS infrastructure. Closes delivery Block 01. Merge commit `2192eda`.

### Added
- An S3 backend with versioning, encryption and `prevent_destroy`, using native S3 locking rather than a DynamoDB table. Commit `d586dc5`.
- A VPC of `10.42.0.0/16` with two public and two private subnets across two availability zones, one NAT gateway, and the subnet tags the load balancer controller needs.
- IAM roles for the cluster, the nodes and the EBS CSI driver.
- An EKS 1.36 cluster with a managed node group of two `t3.large` On-Demand instances in the private subnets. Commit `5047e0c`.
- The `vote-dev` and `vote-prod` namespaces. Commit `fd3c7f5`.
- The EBS CSI driver with an EKS Pod Identity association, and an encrypted `gp3` StorageClass. Commit `0967c66`.

### Changed
- Terraform is split into four independent roots rather than the single root the original plan specified. See [ADR 0017](docs/decisions/0017-terraform-multi-root.md).
- Workload identity uses EKS Pod Identity rather than IRSA. See [ADR 0018](docs/decisions/0018-eks-pod-identity.md).

## [0.1.0] — 2026-10-14

Repository foundation. Closes delivery Block 00. Merge commit `4667c11`.

### Added
- Repository hygiene tests, written in a failing state first in `cecfd3c` and made to pass in `0566c94`.
- Ignore rules for Git and Docker, with allow-list `.dockerignore` files per build context so nothing unexpected enters an image.
- A local Docker Compose stack, and an environment template with keys and no values.
- Password helper scripts for local use. Commit `2d1049f`.

### Removed
- A `.env` symlink pointing into a previous project's secret directory, which Docker Compose loaded automatically and which silently overrode the intended values.
- Committed .NET build output containing another developer's absolute paths.
- A deployment compose file carrying plain-text credentials, a previous project's managed service endpoints, and `NODE_TLS_REJECT_UNAUTHORIZED=0`.

## Earlier history

| Commit | Content |
|---|---|
| `5898c60` | The original pre-implementation design: 16 decision records and a 14-block delivery plan. Preserved in [docs/decisions/initial/](docs/decisions/initial/) and superseded by the current roadmap. |
| `15f2c41` | Repository initialised |

[Unreleased]: https://github.com/asyachin/wtt-demo/compare/v0.8.0...dev
[0.8.0]: https://github.com/asyachin/wtt-demo/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/asyachin/wtt-demo/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/asyachin/wtt-demo/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/asyachin/wtt-demo/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/asyachin/wtt-demo/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/asyachin/wtt-demo/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/asyachin/wtt-demo/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/asyachin/wtt-demo/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/asyachin/wtt-demo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/asyachin/wtt-demo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/asyachin/wtt-demo/releases/tag/v0.1.0
