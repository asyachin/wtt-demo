# Delivery process

Small by design. Its purpose is that any claim in this repository can be traced to a commit, and that a deviation from plan is recorded rather than absorbed.

## Branches

| Branch | Purpose | Merged by |
|---|---|---|
| `main` | Released state | Pull request from `dev` |
| `dev` | Integration branch. Argo CD syncs the application from it. | Pull request |
| `feature/*` | New behaviour | Pull request into `dev` |
| `fix/*` | A correction | Pull request into `dev` |
| `release/*` | Promotes a built image: one line in `k8s/apps/dev/applications.yaml` | Pull request into `dev` |
| `block/*` | A roadmap block | Pull request into `dev` |
| `docs/*` | Documentation only | Pull request into `dev` |

### Why `feature/*` and `release/*` are separate

A code change and the deployment of the image built from it are different events with different risks, so they are different pull requests.

```
feature/vote-landing-page   →  PR #6  →  dev  →  CI builds vote:…-build.21
release/vote-landing-page   →  PR #7  →  dev  →  Argo CD deploys build.21
```

The benefit is that reverting a release returns the cluster to the previous image without reverting the source change, and reverting a source change does not implicitly roll the cluster back. Each is a one-line revert of an independent commit. This was exercised in `3f9d2a6` and `eac7c13`.

## Status values

| Status | Meaning |
|---|---|
| `PLANNED` | Acceptance criteria written and agreed. No work started. |
| `IN PROGRESS` | Work underway. Some criteria may already be met. |
| `BLOCKED` | Cannot proceed. The blocker is named. |
| `CLOSED` | Criteria met, evidence recorded, merged into `dev`. |
| `OPTIONAL` | Valuable, not required for the current objective. No criteria agreed. |

A block moves to `CLOSED` only when every criterion is met. Partial completion stays `IN PROGRESS` with the outstanding items listed, which is why Block 04 is open with four of five scope items delivered.

## Block lifecycle

```
1. Write the acceptance criteria in docs/roadmap.md, before implementation.
2. Branch from dev.
3. Implement. Where a test-first cycle applies, push the failing state first
   so the test is shown to be capable of failing.
4. Verify each criterion. Record the command and its real output.
5. Open a pull request. CI must pass.
6. Merge to dev, update the roadmap and the changelog, tag if it is a release.
```

Branches are kept after merge as implementation evidence.

## Definition of Done

- [ ] Every acceptance criterion verified, with the command and its output recorded
- [ ] CI green: lint, tests, build, Trivy scan
- [ ] Public demonstration still correct — [operations/operate.md](operations/operate.md) section 1 passes
- [ ] No secret, key or token added to the repository
- [ ] `docs/roadmap.md` status and evidence updated
- [ ] `CHANGELOG.md` entry added under the right version
- [ ] Any architectural deviation recorded in `docs/decisions/README.md`, and a new decision record written if an accepted decision is superseded
- [ ] Merged into `dev` by pull request

Two rules keep the checklist meaningful:

- **No criterion may be satisfied by inspection alone.** Each needs a command, an observed output, or a named human observation with a date.
- **Where only a human can verify something** — browser behaviour, a visual check — the record names the observer, the date and the browser. It is not written as though a script proved it. Where a detail such as a browser version was not captured, the record says so rather than inventing one.

## Releases and versioning

`CHANGELOG.md` follows Keep a Changelog; versions follow Semantic Versioning, adapted for a demonstration platform:

| Bump | When |
|---|---|
| Minor, `0.x.0` | A delivery block closes, or a user-visible change ships |
| Patch, `0.x.y` | A fix or a security update |

At each release:

1. Move the relevant `[Unreleased]` entries under a new version heading with its date.
2. Link the version to its merge commit or pull request.
3. Add the comparison link at the foot of the file.
4. Tag the merge commit:

```bash
git tag -a v0.9.0 <merge-commit> -m "Block NN: short description"
git push origin v0.9.0
```

The tags `v0.1.0` through `v0.8.0` were created on 2026-10-15 and applied to commits that already existed. The changelog states this, so no release date is implied to be the date its tag was created.

## Image versions

Computed by CI, never by hand:

```
YYYY.MM.DD-HHMM-build.<run number>-a<attempt>-<short sha>
2026.10.15-1626-build.27-a1-8968dc4
```

Each service also receives a second tag carrying the full commit SHA, so an image can be found by commit without knowing its build number. Nothing is ever tagged `latest`. Rationale: [decisions/0021-ci-image-versioning.md](decisions/0021-ci-image-versioning.md).

## Change control

For a deviation discovered mid-block, before implementing it:

```
1. State the technical reason and the impact on the live demonstration.
2. If an accepted decision is affected, write the superseding record first.
3. Implement on the branch.
4. Verify, and record the evidence.
5. Merge, and update the roadmap, the changelog and the decision index.
```

The step most often skipped is the second. A decision record edited after the fact destroys the only evidence of what was believed and when.

## Decision records

[ADR 0001](decisions/initial/0001-record-architecture-decisions.md) established that a record is never edited once accepted, only superseded. That is honoured literally, including status fields.

The original sixteen records are therefore preserved byte-for-byte in [decisions/initial/](decisions/initial/) even where implementation contradicted them. Current applicability is tracked separately in [decisions/README.md](decisions/README.md), which is a living index rather than a record.

Records written after the fact carry an explicit `Recorded` field stating they are retrospective and naming the commits they were reconstructed from. No record is given a date earlier than the day it was written.

## What this process does not have

No approval gates, no sign-off matrix, no templates beyond the roadmap entry. For a single-engineer project those would be ceremony. The three things it does enforce:

- acceptance criteria written before implementation,
- evidence recorded at the time of verification,
- deviations recorded rather than smoothed over.
