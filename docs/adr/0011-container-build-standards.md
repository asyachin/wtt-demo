# 0011 — Multi-Stage Builds, Non-Root, Pinned, Labelled

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The three inherited Dockerfiles are inconsistent. `vote` is multi-stage with `base`, `dev`, and `final`. `worker` is multi-stage with an SDK build stage. `result` is a single stage that installs `nodemon` globally and ships it to production.

All three run as root. None sets a `USER`. None carries metadata labels. `app/vote/requirements.txt` has no version specifiers at all, so two builds of the same commit a week apart can produce different images. `vote` has no `.dockerignore`, so `COPY . .` copies whatever happens to be in the directory. All three bake default database credentials into the image as `ENV`.

The target namespaces enforce the `restricted` Pod Security Standard, which rejects a container that runs as root.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| One build pattern for all three images, enforced by tests | Consistent. Reviewable. Each property is permanent because a test holds it. | Rewriting three Dockerfiles, and the size budgets take iteration to meet |
| Fix only what blocks deployment, which is the root user | Fastest route to a running system | The rest of the problems stay, and every one of them is something a reviewer will notice |
| Use distroless base images | Smallest, smallest attack surface | No shell, so no `kubectl exec` to debug and no `curl` for a container health check. For a demonstration that has to be opened up and explained, that cost is too high. |
| Build with Buildpacks | No Dockerfile to write | Hides the build, which is the opposite of what this project is demonstrating |

## Decision

Every image follows the same four-stage pattern, so that one mental model covers all three services:

```
FROM <base> AS base      # runtime dependencies only, shared by both outputs
FROM base  AS build      # compilers and package managers. Never shipped.
FROM base  AS dev        # base plus development tooling. Produces the -dev image.
FROM base  AS runtime    # base plus the artefact from build. Produces the production image.
```

Mandatory for every image:

| Rule | Reason |
|---|---|
| At least two stages | Build tools never reach the production image |
| A `USER` that is not root or 0 | `restricted` Pod Security rejects root |
| Base image pinned by digest, never `:latest` | A reproducible build, and a scan result that means something |
| Every direct dependency pinned to an exact version | The same commit produces the same image |
| A `.dockerignore` in every service directory | The build context carries no secret and no stray file |
| No credential in an `ENV` instruction | A default password in an image is a password that gets used |
| The five OCI labels, filled at build time | An image can be traced to a commit a year later |
| A size budget, enforced by a test | Bloat has to be argued for rather than simply added |
| No development tooling in the `runtime` stage | A smaller attack surface |

Budgets: `vote` under 220 MB, `result` under 250 MB, `worker` under 230 MB. A budget may be raised in the same pull request with the reason in the commit message. A budget may not be deleted.

## Reasoning

One pattern across three languages is worth more than three locally optimal Dockerfiles. Anybody reading `result/Dockerfile` after reading `vote/Dockerfile` already knows the shape, and the stage names map directly onto the two published images described in [0006](0006-registry-and-image-tags.md).

Pinning is the foundation that the rest of the security work stands on. An unpinned base image means a Trivy result from last week says nothing about the image running today, which makes the whole scanning effort theatre. The same applies to unpinned Python dependencies.

Non-root is not optional, because the namespaces enforce `restricted`. Doing it in Block 01 rather than in Block 12 means the images are correct before the policy arrives, instead of the policy rejecting the images and forcing a rushed fix.

The size budget as a test is the part that is unusual and that keeps working. Image size creeps up one package at a time, each one justified on its own, and nobody notices for months. A failing test forces the conversation at the moment the package is added.

Distroless was rejected deliberately. It would give the smallest images and the smallest attack surface, and it would also remove the shell. This project will be opened in an interview, and `kubectl exec` into a pod to show a readiness check is worth more than 40 MB. The runbooks also use `exec` with `curl` and `nc` in several procedures. That is a conscious trade of attack surface for operability, and it is the sort of trade that should be visible rather than silent.

## Consequences

### Positive

- One pattern for three languages, so one review habit covers all of them.
- Builds are reproducible, which makes vulnerability scanning meaningful.
- The images pass `restricted` Pod Security from Block 01 onward.
- No credential is baked into any image.
- Every image can be traced to a commit through its labels.
- Size stays bounded, permanently, because a test holds it.

### Negative

- Digest pinning means base image updates are manual. A pinned digest does not receive security patches. Dependabot is configured to raise the digest, and a stale digest will show up as Trivy findings in Block 12, which is the signal to update.
- `readOnlyRootFilesystem` in Block 12 requires an `emptyDir` for every path a service writes to, and finding all of them is trial and error.
- Building two targets per service roughly doubles the build step in the pipeline.
- Keeping a shell in the image is a larger attack surface than distroless. Accepted, and stated.
- The size budgets will need at least one raise over the project's life, and each raise is a small argument.

### Neutral

- `hadolint` enforces the mechanical rules, and `tests/unit/test_dockerfiles.py` enforces the ones a linter cannot see, such as the presence of a non-root user in the final stage.

## Verification

Block 01, static, from the Dockerfile text:

- `test_all_dockerfiles_are_multistage`
- `test_all_images_declare_non_root_user`
- `test_base_images_are_pinned_by_digest_or_exact_tag`
- `test_no_dev_tooling_in_runtime_stage`
- `test_required_labels_present`
- `test_python_requirements_are_pinned`

Block 01, against the built images:

- `test_image_runs_as_non_root`
- `test_image_size_budget`
- `test_no_package_manager_cache_in_image`
- `test_image_has_source_label`

Block 12, in the cluster:

- `test_root_pod_is_rejected`
- `test_all_containers_read_only_root`

## Revisit When

Operability no longer needs a shell in the image, which makes distroless the better trade. Or a service needs a build step that does not fit the four-stage pattern, in which case the pattern is extended rather than abandoned.
