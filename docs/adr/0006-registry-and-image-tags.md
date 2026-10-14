# 0006 — Use GHCR, and Tag Two Images With One Identifier

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

Images have to be stored somewhere and named somehow.

There is a specific requirement: each service produces a development image and a production image, and it must be possible to say with certainty which development image a given production image belongs to. The tag must contain both a commit hash and a build time.

The previous project used a personal Docker Hub account with tags like `vote-image:latest` and `result-image-original`. Nothing about that is traceable to a commit.

## Options Considered

### Registry

| Option | Advantage | Disadvantage |
|---|---|---|
| GitHub Container Registry | Same identity as the source. Free for public packages. Keyless signing with the Actions identity works without configuration. Packages link back to the repository. | Outside AWS, so image pulls cross the internet |
| AWS ECR | Inside AWS, pulls stay on the AWS network, IAM-based access | Another Terraform resource. CI needs an AWS role to push. Not publicly browsable by a reviewer without an account. |
| Docker Hub | Familiar | Rate limits on anonymous pulls, which breaks a node that restarts |

### Tag scheme

| Option | Advantage | Disadvantage |
|---|---|---|
| `<semver>-<timestamp>-g<sha>` | Human-readable ordering, build time without an API call, and a commit reference | Long |
| Commit hash only | Short and exact | No ordering, and no build time |
| `latest` plus a hash | Convenient | `latest` makes "what is running" unanswerable and defeats rollback |
| Semantic version only | Clean | Two builds of the same commit are indistinguishable |

## Decision

All images are in GHCR under `ghcr.io/asyachin/`, as public packages.

The tag format is:

```
<semver>-<utc timestamp>-g<short sha>
0.3.0-20261014T120533Z-g1a2b3c4
```

Each service produces two images with that identical tag: `wtt-<service>-dev` built from the `dev` stage, and `wtt-<service>` built from the `runtime` stage. Nothing is ever tagged `latest`. Production images are signed with `cosign` in keyless mode.

## Reasoning

GHCR wins on identity. The source is already on GitHub, so there is one account, one set of permissions, and one audit trail. Keyless `cosign` signing uses the workflow's own OpenID Connect identity, which means there is no signing key to store, lose, or rotate, and a successful verification proves the image was built by a workflow in this repository rather than pushed from a laptop. Setting that up against ECR is more work for the same result.

Public packages remove the need for an image pull secret in the cluster, which removes a secret from the system entirely, and they let a reviewer inspect any image without an account.

The tag carries three pieces of information because each one answers a different question. The semantic version answers which release line. The UTC timestamp answers when, sorts correctly as plain text, and needs no registry lookup. The commit hash answers which source. The `g` prefix follows the `git describe` convention and keeps the field unambiguous when a hash starts with a digit.

The tag is computed once per pipeline run by `scripts/image-tag.sh` and passed to every later step. Computing it twice would produce two timestamps, and the two images would no longer share a tag, which is the whole point.

### The trade-off that has to be stated

The two images share a tag but **not** a digest. They are built from different stages, so they contain different files.

The alternative, building once and applying two tags, would give a shared digest. It was rejected because it would mean one artefact, and that artefact would either carry the development tooling into production or lack it in development. Shipping `nodemon` and a file watcher into a production image to gain a tidy digest is the wrong trade.

The consequence is handled explicitly rather than hidden: the production target is the only artefact that evidence is collected about. The `integration` job in CI tests the production target. Trivy scans the production images. `cosign` signs the production images. Nothing from a development image is ever promoted. The development image is a convenience for local work and for the `vote-dev` namespace.

## Consequences

### Positive

- One identity system for source and images.
- One tag links a production artefact, a development artefact, a commit, and a build time.
- No image pull secret exists anywhere.
- Keyless signing with no key to manage, verifiable by anybody.
- An immutable tag makes rollback exact and makes "what is running" answerable.

### Negative

- The two images are not bit-identical, so a result from the development image is not evidence about the production image. This is mitigated by testing the production target, and it cannot be removed.
- Pulls cross the internet from AWS to GHCR. For six small images pulled rarely, the cost and latency are negligible, but the cluster now depends on GitHub availability for a node restart.
- Public packages mean anybody can pull and inspect the images. For a demonstration this is a feature; for real software it would need thought.
- The tag is long, which makes `kubectl describe` output wide.
- Pipeline time roughly doubles for the build step, because every service is built twice.

### Neutral

- GHCR retention has to be managed. A cleanup workflow keeps the last 20 tagged versions per image and never deletes the tag referenced by `values-prod.yaml`.

## Verification

- `test_tag_format` and `test_tag_is_stable_within_one_invocation` in Block 04.
- `test_dev_and_prod_share_one_tag` in Block 04.
- `test_no_latest_tag` in Block 04, which scans every workflow.
- `test_tag_pair_exists_in_registry` in Block 04, against the real registry.
- `test_cosign_verify_passes_for_running_image` in Block 12, against the image actually running in production.

## Revisit When

Image pull traffic becomes a cost or a reliability concern, which would mean ECR with a pull-through cache. The tag scheme would not change.
