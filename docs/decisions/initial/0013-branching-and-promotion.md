# 0013 — Two Branches, Auto-Merge Into Dev, Manual Promotion

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

Argo CD tracks a Git branch per environment, so the branch model and the environment model are the same thing. Whatever branches exist, those are the environments.

The requirement is that a push runs tests, and that a green test run merges automatically into `dev`, where both images are built with a shared tag. The production image then flows to GHCR and from there to Argo CD.

The work itself arrives as 14 sequential blocks, each in its own branch, each pushed twice: once in a failing state and once passing.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| `main` and `dev`, with automatic merge into `dev` and manual promotion to `main` | Matches the two namespaces exactly. Production changes only by a deliberate act. | Two long-lived branches to keep from diverging |
| Trunk-based, `main` only, with environments by tag | One branch, no divergence | Argo CD would track a tag or a path rather than a branch, and every commit would reach production or need a feature flag |
| GitFlow with `release` and `hotfix` branches | Well known | Far too much ceremony for one person and two environments |
| Automatic promotion to `main` when the dev end-to-end tests pass | Fully automatic | Nothing stops a bad change except the tests. For a system that will be opened in an interview, a human reading the diff is worth more than the saved minute. |

## Decision

Two protected branches:

| Branch | Environment | How a change arrives |
|---|---|---|
| `dev` | namespace `vote-dev` | Automatically, by auto-merge, when `ci-complete` is green |
| `main` | namespace `vote-prod` | By hand, through a promotion pull request that copies a tag |

Work branches are `block/NN-name` for a block in the plan and `fix/short-name` for anything else. Both are short-lived and are deleted after the merge.

Auto-merge is enabled on pull requests into `dev`, with one exception: a pull request touching `infra/**` or `deploy/argocd/**` is excluded and must be merged by a human.

Promotion is a pull request into `main` whose diff contains nothing but image tags. It must answer four questions: which tag, what changed since the tag in production, which tests were run against `vote-dev` and with what result, and what the rollback step is.

Every block is pushed twice. The failing push comes first.

## Reasoning

The branch count follows from the environment count. Two namespaces, two branches, and Argo CD reads one each. Adding a third branch would mean adding a third namespace, and removing one would mean the two environments share a source of truth, which defeats the point of having two.

Auto-merge into `dev` is safe because `dev` is where a change is proven. The gate is `ci-complete`, which depends on linting, unit tests, the build, and the integration tests. A change that passes all of those is good enough for a non-public namespace, and the merge does not need a human.

Manual promotion to `main` is where the asymmetry is deliberate. The cost of a human reading a tag diff is about a minute. The benefit is that production never changes without somebody choosing to change it, and that the four questions in the pull request body force a moment of thought about what is being shipped and how to undo it. For a system whose public URL is on a job application, that is the right trade.

The carve-out for `infra/**` matters more than it looks. An application change is reversible in five minutes with `git revert`. A Terraform change can delete a volume, orphan a load balancer that keeps billing, or recreate a cluster. A robot should not merge that. Application changes and infrastructure changes have different blast radii, so they get different rules.

The requirement that the promotion diff contains only tags exists so that a rollback is surgical. If a promotion carries a chart change as well, reverting the bad release also reverts the chart, and the two have to be separated during an incident, which is the worst time to do it.

Pushing the failing state first is the only mechanical evidence that the tests were written before the implementation. A branch that arrives green proves nothing about the order, and the failing CI run is a permanent record in the pull request that each test is capable of failing. A test that has never failed has never been shown to test anything.

## Consequences

### Positive

- The branch model and the environment model are the same, so there is nothing to reconcile.
- Development moves without ceremony; production does not move by accident.
- Rollback is `git revert` on a diff that contains only tags.
- Infrastructure changes always get human review.
- The test-first order is visible in the pull request history rather than claimed.

### Negative

- `dev` and `main` diverge between promotions, so a hotfix to production has to go through `dev` first or be cherry-picked, and cherry-picking risks the two branches drifting.
- Promotion is manual, so production can lag behind `dev` simply because nobody has opened the pull request.
- Auto-merge depends on branch protection being configured correctly in GitHub. That configuration is not in Git, so it is not reproducible with the rest of the project. It is written down in the Block 00 pull request instead, which is weaker.
- Two pushes per block is extra work, and the discipline is easy to lose under time pressure.
- Squash merging loses the individual commits of a block, including the separation between the test commit and the implementation commit. The pull request keeps them, so the evidence survives, but `git log` on `dev` does not show it.

### Neutral

- Conventional Commits are used, which makes the changelog mechanical.
- Git tags mark milestones only: `v0.1.0` after Block 05, `v0.2.0` after Block 08, `v1.0.0` after Block 13. Image tags are a separate scheme, described in [0006](0006-registry-and-image-tags.md).

## Verification

- `test_infra_changes_excluded_from_auto_merge` in Block 04.
- `test_bot_commit_skips_ci` in Block 04, which prevents the tag-update commit from triggering an endless pipeline loop.
- `test_dev_app_tracks_dev_branch` and `test_prod_app_tracks_main_branch` in Block 08.
- `test_rollback_by_revert` in Block 08, which performs a real rollback with no manual cluster change.
- Branch protection on GitHub requires `ci-complete` and blocks force pushes.

## Revisit When

A second engineer joins, which makes review on `dev` worth its cost. Or the number of environments changes, which changes the number of branches with it.
