# Container Images and Tags

## Registry

All images live in GitHub Container Registry under the repository owner.

```
ghcr.io/asyachin/wtt-vote
ghcr.io/asyachin/wtt-vote-dev
ghcr.io/asyachin/wtt-result
ghcr.io/asyachin/wtt-result-dev
ghcr.io/asyachin/wtt-worker
ghcr.io/asyachin/wtt-worker-dev
```

The packages are public, so no pull secret is needed in the cluster and a reviewer can inspect any image without an account. The reasoning for GHCR instead of ECR is in [ADR 0006](../adr/0006-registry-and-image-tags.md).

## Tag Format

```
<semver>-<utc timestamp>-g<short sha>

0.3.0-20261014T120533Z-g1a2b3c4
```

| Part | Example | Source | Answers |
|---|---|---|---|
| Semantic version | `0.3.0` | The `VERSION` file at the repository root | Which release line is this |
| UTC timestamp | `20261014T120533Z` | `date -u +%Y%m%dT%H%M%SZ`, computed once per pipeline run | When was it built, without an API call, and it sorts correctly as text |
| Short commit | `g1a2b3c4` | `git rev-parse --short=7 HEAD` | Which commit produced it |

The `g` prefix follows the `git describe` convention and keeps the field unambiguous when the hash begins with a digit.

Nothing is ever tagged `latest`. A moving tag makes it impossible to say what is running, and it defeats both the rollback procedure and the signature verification.

The tag is computed by `scripts/image-tag.sh`, which is used by CI and is available locally. It is computed **once** per pipeline run and passed to every later step. Computing it twice would give two different timestamps, and the development and production images would no longer share a tag.

## Two Images, One Tag

For each service, a pipeline run builds two images from the same Dockerfile and the same commit, with the same tag.

| Image | Build target | Contains | Runs in |
|---|---|---|---|
| `wtt-<service>-dev:<tag>` | `dev` | The runtime plus development tooling: a file watcher for `vote`, `nodemon` for `result`, debug symbols for `worker`. Verbose logging by default. | Namespace `vote-dev`, and a laptop |
| `wtt-<service>:<tag>` | `runtime` | Only what is needed to serve. No build tools, no package manager cache, no shell utilities beyond what the health check needs. | Namespace `vote-prod` |

### What the Shared Tag Buys

Given a running production image, the exact development image it was built alongside is known without looking anything up:

```
# Running in production
ghcr.io/asyachin/wtt-vote:0.3.0-20261014T120533Z-g1a2b3c4

# Its development counterpart, same commit, same pipeline run
ghcr.io/asyachin/wtt-vote-dev:0.3.0-20261014T120533Z-g1a2b3c4

# The commit
git show 1a2b3c4
```

That is the traceability requirement: one identifier links a production artefact, a development artefact, a commit, and a build time.

### What the Shared Tag Does Not Buy

The two images are **not** bit-identical and do not share a digest. They are built from different stages, so they contain different files. This is a real limitation and it must be stated rather than hidden:

- A test that passes against the development image is not proof about the production image, because the two have different dependency trees.
- For that reason the `integration` job in CI tests the **production** target, not the development target. The development image is a convenience for local work and for the development namespace, never the artefact that evidence is collected about.
- Trivy scans and `cosign` signatures are produced for the **production** images only. Nothing from the development images is ever promoted.

The alternative, building one image and tagging it twice, would give a shared digest but would also ship the development tooling into production, which is worse. The trade-off is recorded in [ADR 0006](../adr/0006-registry-and-image-tags.md).

## Build Stages

Every Dockerfile follows the same shape, so that one mental model covers all three services.

```
FROM <base> AS base         # runtime dependencies only, shared by both outputs
FROM base  AS build         # compilers, headers, package managers. Never shipped.
FROM base  AS dev           # base plus development tooling. Output: the -dev image.
FROM base  AS runtime       # base plus the artefact from build. Output: the production image.
```

### vote, Python

| Stage | Does |
|---|---|
| `base` | `python:3.11-slim` pinned by digest, creates the user `app`, installs `curl` for the health check |
| `build` | Creates a virtual environment in `/opt/venv` and installs the pinned `requirements.txt` |
| `dev` | Copies the virtual environment, adds `watchdog`, runs the Flask development server |
| `runtime` | Copies the virtual environment and the source, runs `gunicorn` as `app` |

### result, Node.js

| Stage | Does |
|---|---|
| `base` | `node:18-slim` pinned by digest, uses the built-in `node` user, installs `tini` |
| `build` | `npm ci --omit=dev` |
| `dev` | Copies `node_modules`, adds `nodemon` |
| `runtime` | Copies `node_modules` and the source, runs `node server.js` as `node` |

### worker, .NET

| Stage | Does |
|---|---|
| `base` | `mcr.microsoft.com/dotnet/runtime:8.0` pinned by digest, creates the user `app` |
| `build` | `dotnet restore` then `dotnet publish -c Release` on the SDK image |
| `dev` | Copies the Debug build, keeps the debug symbols |
| `runtime` | Copies the Release output, runs `dotnet Worker.dll` as `app` |

## Size Budgets

Enforced by `tests/integration/test_image_properties.py::test_image_size_budget`. The budget exists so that bloat has to be argued for rather than simply added.

| Image | Budget | Starting point |
|---|---|---|
| `wtt-vote` | 220 MB | about 190 MB |
| `wtt-result` | 250 MB | about 230 MB |
| `wtt-worker` | 230 MB | about 215 MB |

A budget may be raised, in the same pull request, with the reason in the commit message. A budget may not be deleted.

## Required Labels

Every image carries these, filled in at build time by `--build-arg`:

```
org.opencontainers.image.source       https://github.com/asyachin/wttcampusone
org.opencontainers.image.revision     <full commit sha>
org.opencontainers.image.created      <rfc3339 build time>
org.opencontainers.image.version      <the full tag>
org.opencontainers.image.title        wtt-vote
org.opencontainers.image.licenses     MIT
```

`org.opencontainers.image.source` makes the GitHub package page link back to the repository automatically. `revision` means that an image pulled a year from now can still be traced to a commit, even if the tag is gone.

## Signing and Verification

Production images are signed by the publishing workflow with `cosign` in keyless mode, using the GitHub Actions workload identity. There is no key to store, lose, or rotate.

```
cosign verify ghcr.io/asyachin/wtt-vote:0.3.0-20261014T120533Z-g1a2b3c4 \
  --certificate-identity-regexp 'https://github.com/asyachin/wttcampusone/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

A successful verification proves that the image was built by a workflow in this repository, and not pushed by hand from a laptop. Verification is a required step in the promotion procedure in [git-workflow.md](git-workflow.md) and is checked in the cluster by `test_cosign_verify_passes_for_running_image` in Block 12.

A software bill of materials is generated for each production image and attached to the GitHub release draft, so a reviewer can see the full dependency tree without pulling the image.

## Where the Tag Lives After the Build

```
scripts/image-tag.sh                              computes it
  │
GitHub Actions publish workflow                   builds and pushes six images with it
  │
deploy/helm/wtt-vote/values-dev.yaml              written by CI, on branch dev
  │
Argo CD                                           syncs namespace vote-dev
  │
deploy/helm/wtt-vote/values-prod.yaml             copied by hand in a promotion PR
  │
Argo CD                                           syncs namespace vote-prod
```

The tag appears in exactly two files in Git, and both are environment value files. It never appears in `values.yaml`, which is checked by `test_no_image_tag_in_default_values`. A default tag would silently become the deployed version whenever an overlay forgot to set one.

## Retention

GHCR keeps every tag. A cleanup workflow removes untagged manifests older than 30 days and keeps the last 20 tagged versions per image. The tag currently referenced by `values-prod.yaml` is never deleted, which is checked before the cleanup runs.
