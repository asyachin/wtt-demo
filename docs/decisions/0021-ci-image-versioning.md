# 0021 — CI image versioning and a blocking Trivy gate

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-15 |
| Deciders | Alexander Syachin |
| Block | 07 |
| Supersedes | The dual dev/prod image tag scheme in [ADR 0006](initial/0006-registry-and-image-tags.md), and the non-blocking Trivy design in [ADR 0012](initial/0012-testing-strategy.md) |
| Superseded by | none |
| **Recorded** | **Retrospectively, 2026-10-15, reconstructed from commits `6a05570`, `5e7d360`, `11b36e6` and `8625709`. The decision was made during implementation and was not written down at the time.** |

## Context

[ADR 0006](initial/0006-registry-and-image-tags.md) specified a tag of the form `<semver>-<timestamp>-g<sha>`, a paired development and production image built from different Dockerfile stages, cosign signing, and a software bill of materials. [ADR 0012](initial/0012-testing-strategy.md) specified that a vulnerability scan should report findings without blocking a build, reasoning that a base-image finding with no available fix should not stop all delivery.

Block 07 implemented GitHub Actions and built something narrower on both points: one image per service, a different tag format, and a scan that **blocks** the build on a `CRITICAL` finding. Neither change was written down at the time.

## Options

### Tag scheme

| Option | Advantage | Disadvantage |
|---|---|---|
| **`YYYY.MM.DD-HHMM-build.<run>-a<attempt>-<sha>`, plus a second tag with the full SHA** | Sortable as text, states exactly when and from what run an image came, and a full-SHA tag means an image can be found from a commit with no build metadata | Longer than the original scheme |
| The planned `<semver>-<timestamp>-g<sha>` | Also sortable, includes a semantic version | Requires maintaining a semantic version number for a demonstration with one consumer; nothing reads it |
| Short commit SHA only, as used before CI existed | Short | No build time, and two images from the same commit are indistinguishable if the Dockerfile output ever differs run to run |

### Image pairing

| Option | Advantage | Disadvantage |
|---|---|---|
| **One image per service** | Half the build and scan time; one artefact to reason about | No separate development variant |
| Paired dev and prod images, as planned | A development image with extra tooling | This project has one environment. A development image would have nothing to be developed against. |

### Vulnerability gate

| Option | Advantage | Disadvantage |
|---|---|---|
| **Blocking on `CRITICAL`, `ignore-unfixed: true`** | A vulnerable image is never published. The `ignore-unfixed` flag means the gate cannot block on something with no available remedy. | A `CRITICAL` finding does stop delivery until fixed |
| Non-blocking, as planned, with later triage | Delivery never halts | The project has no later-triage step — no CI existed to run the report, so "non-blocking" meant "not run" |

## Decision

```
YYYY.MM.DD-HHMM-build.<run number>-a<attempt>-<short sha>
2026.10.15-1626-build.27-a1-8968dc4
```

Computed once per workflow run. Each service also receives a second tag carrying the full commit SHA. One image per service, built with `docker buildx`, loaded locally, scanned, and only pushed if the scan passes:

```yaml
- Build image locally        # load: true, push: false
- Scan image with Trivy      # severity: CRITICAL, ignore-unfixed: true, exit-code: 1
- Publish verified image     # docker push, both tags — only reached if the scan passed
```

## Reasoning

**The tag answers the questions that matter here.** Build time, build number, attempt number and commit are all legible without a lookup. The second, full-SHA tag exists because `git log` and GitHub both show the full SHA, so an engineer with a commit in hand can find its image without first computing a short form or knowing the build number.

**One image per service matches one deployed environment.** [ADR 0006](initial/0006-registry-and-image-tags.md)'s dev/prod pair existed to support a promotion workflow between two environments. Only one environment is deployed; see [ADR 0003's applicability note](README.md). Building a second image with nothing to consume it would be waste, not safety.

**Blocking on `CRITICAL` was the practical choice for a project with no later triage step.** ADR 0012's reporting-only design assumed a security review process that reads scan output and acts on it on a cadence. That process does not exist here, and the engineer is also the only reader of any report CI would produce. A gate that blocks is a report that cannot be ignored. `ignore-unfixed: true` is the compromise that keeps this from becoming unworkable: a vulnerability with no vendor-provided fix cannot be acted on by changing a version number, so it does not block.

**The gate has already proven its value**, which is the strongest argument for keeping it. It stopped a release and named two real vulnerable dependencies, `express` and `StackExchange.Redis`, which were then upgraded. See version 0.7.1 in `CHANGELOG.md`. A gate that has never fired is unproven; this one has.

**Build, scan, then push — in that order.** The image is built with `load: true, push: false`, so it exists locally for scanning before the registry ever sees it. A vulnerable image is therefore never public, rather than public and flagged.

**No signing, no SBOM.** Both were planned and both are dropped for now. Keeping an accurate and enforced tag plus a working vulnerability gate was judged more valuable than adding provenance attestations nobody yet consumes. Deferred, not rejected.

## Consequences

### Positive

- Every published image states when it was built and from which commit, legibly.
- A vulnerable image cannot reach the registry; the gate is proven, having blocked a real release.
- Half the build and scan time of the planned dual-image scheme.
- Build, scan and publish are separated into distinct workflow steps, so a scan failure is unambiguous and does not leave a partially pushed image.

### Negative

- **`CRITICAL` findings halt delivery entirely**, with no fallback once a fix does not yet exist for a given CVE. For a project with only one engineer to triage, that risk is accepted; for a team, it would need the non-blocking path ADR 0012 originally specified, with a real review cadence behind it.
- **No development image exists.** If a second environment is ever built, this decision will need revisiting alongside ADR 0003.
- **No image signing or SBOM.** Supply-chain provenance claims cannot currently be verified beyond "this came from the CI workflow that has access to push to GHCR."
- The tag is long, which makes `kubectl describe` output and manifest diffs harder to scan visually.
- `HIGH` severity findings are not scanned for at all; only `CRITICAL`. A `HIGH` vulnerability can ship unnoticed.

### Neutral

- The version string has no semantic meaning — it cannot be compared for "newer" versus "older" beyond its date prefix, which happens to sort correctly as plain text.

## Verification

```bash
# Tag format
grep -A3 'image_tag=' .github/workflows/ci-images.yml

# Build happens before scan, scan before push
grep -nE 'Build image locally|Scan image|Publish verified' .github/workflows/ci-images.yml

# The gate is configured to block, not report
grep -A6 'aquasecurity/trivy-action' .github/workflows/ci-images.yml
```

A real instance of the gate firing: `git log --oneline v0.7.0..v0.7.1` and the Trivy step output recorded in that pull request.

## Revisit when

A second environment is deployed, which reopens the dev/prod image question. Or a team larger than one engineer takes over, which reopens whether a blocking `CRITICAL` gate with no override path is still the right trade.
