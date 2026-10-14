# Git Workflow

## Branches

| Branch | Protected | Meaning | Argo CD |
|---|---|---|---|
| `main` | yes | What runs in production | Application `vote-prod` tracks it |
| `dev` | yes | What runs in the development namespace, and the integration point for all work | Application `vote-dev` tracks it |
| `block/NN-name` | no | One block from the deployment plan | none |
| `fix/short-name` | no | A correction that does not belong to a block | none |

There are no long-lived feature branches. A block branch lives hours or days, not weeks.

## The Cycle for One Block

```
git switch dev
git pull --ff-only
git switch -c block/02-app-contract

# 1. RED
#    Write the tests from the block description. Run them. They must fail.
make test-unit                       # fails, on purpose
git add tests/
git commit -m "test(vote): add failing tests for health, readiness and metrics"
git push -u origin block/02-app-contract
#    The CI run fails. That failing run is the evidence that the tests test something.

# 2. GREEN
#    Write the implementation.
make test-unit                       # passes
make test-integration                # passes
git add app/
git commit -m "feat(vote): add health, readiness and metrics endpoints"
git push

# 3. Documentation and status, in the same branch
git add docs/
git commit -m "docs: mark defects D1 to D5 as fixed in block 02"
git push

# 4. Pull request into dev
gh pr create --base dev --fill
#    CI runs. When ci-complete is green, auto-merge squashes it.

# 5. Clean up
git switch dev && git pull --ff-only
git branch -d block/02-app-contract
```

Both the RED push and the GREEN push are required. A branch that arrives already green does not show that the tests were written first, and the point of pushing RED is to prove the test can fail.

## Commit Messages

Conventional Commits, in English, in the imperative mood.

```
<type>(<scope>): <what changed, lower case, no full stop>

<why it changed, if it is not obvious>

<footer: refs, breaking changes>
```

| Type | Use for |
|---|---|
| `feat` | New behaviour in the application or the platform |
| `fix` | A defect correction |
| `test` | Tests only. Every RED commit is a `test` commit. |
| `docs` | Documentation only |
| `refactor` | No behaviour change |
| `build` | Dockerfiles, dependencies, Makefile |
| `ci` | Workflows |
| `infra` | Terraform |
| `deploy` | Helm chart or Argo CD manifests |
| `chore` | Everything else |

Scopes in use: `vote`, `result`, `worker`, `db`, `helm`, `argocd`, `terraform`, `ci`, `docs`, `obs`, `sec`.

Examples:

```
test(worker): add failing test for duplicate vote rows
fix(worker): replace insert with on-conflict upsert

The votes table had no primary key, so the fallback update branch was
unreachable and a second vote from the same visitor added a row instead
of replacing one. Vote totals were higher than the number of voters.

Refs: docs/arch/application.md defect D1
```

Rules:

- English only. This applies to commit messages, code comments, log output, and user interface text.
- One logical change per commit. A commit that fixes a defect and reformats a file is two commits.
- A commit message says why. The diff already says what.
- No `wip`, no `fixes`, no `asdf`, no empty messages.
- Never commit a secret. If one is committed, rotate the value immediately and then deal with the history. Rotating comes first; a value that was pushed is a value that leaked, whether or not the history is rewritten.

## Merging into `dev`

Branch protection on `dev`:

- The status check `ci-complete` must pass.
- The branch must be up to date with `dev` before merging.
- Squash merge only. One block becomes one commit on `dev`.
- Force push is blocked.
- Auto-merge is enabled.

Auto-merge is on by default, with one exception. A pull request that touches `infra/**` or `deploy/argocd/**` is excluded and must be merged by hand. Application changes are reversible in a minute. An infrastructure change can cost money or delete a volume, and that deserves a human reading the plan.

## Promotion from `dev` to `main`

Promotion is a deliberate act, written by hand, and it is the only thing that changes production.

```
# 1. Read the tag that is currently running in the dev namespace
grep -A1 'vote:' deploy/helm/wtt-vote/values-dev.yaml

# 2. Confirm the dev namespace is healthy and the end-to-end tests pass
argocd app get vote-dev
pytest -m e2e --base-url http://localhost:8080   # through a port-forward

# 3. Verify the signature of the production images that carry that tag
cosign verify ghcr.io/asyachin/wtt-vote:<tag> \
  --certificate-identity-regexp 'https://github.com/asyachin/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# 4. Copy the same tag into the production value file
git switch -c promote/<tag>
#    edit deploy/helm/wtt-vote/values-prod.yaml
git commit -m "deploy(prod): promote <tag>"
gh pr create --base main --title "Promote <tag> to production" --body-file -

# 5. Merge by hand after reviewing the diff. Argo CD syncs vote-prod.
```

The promotion diff must contain nothing but image tags. If it contains a chart change as well, split it into two pull requests, so that a rollback of the release does not also roll back the chart.

The promotion pull request body must answer four questions:

1. Which tag is being promoted, and when was it built?
2. What changed since the tag currently in production?
3. Which tests were run against `vote-dev`, and what was the result?
4. What is the rollback step if this goes wrong?

## Rollback

| Situation | Action | Time to recover |
|---|---|---|
| A bad release in production | `git revert` the promotion commit on `main` and push | under 5 minutes, limited by the Argo CD sync interval |
| A bad release in development | Promote nothing. Fix forward on a new branch. | not applicable |
| A bad chart change | Revert the chart commit. The image tag is untouched. | under 5 minutes |
| A bad infrastructure change | Check out the previous commit of the module and run `terraform apply`. State history is in the versioned S3 bucket. | 5 to 30 minutes, depending on the resource |
| A bad migration | Restore the database from the nightly backup, using the runbook. Then fix the migration. | the measured time recorded in Block 11 |

Rollback is always a Git operation. Nobody runs `kubectl rollout undo` or `helm rollback` by hand, because Argo CD would revert it within the next sync and the cluster would end up in a state that Git does not describe.

## Tags and Releases

- Image tags are produced by CI and are described in [images-and-tags.md](images-and-tags.md). They are not Git tags.
- A Git tag is created only when `main` reaches a milestone: `v0.1.0` after Block 05, `v0.2.0` after Block 08, `v1.0.0` after Block 13.
- `CHANGELOG.md` gets one entry per block, written when the block closes, not at the end.

## Pull Request Checklist

The template in `.github/pull_request_template.md` carries this list. It is short on purpose, so that it actually gets read.

```
- [ ] The RED commit was pushed and the CI run failed before the implementation
- [ ] All tests for this block pass in CI
- [ ] The block status is updated in docs/roadmap.md
- [ ] Any new decision is recorded as an ADR
- [ ] No secret is added to the repository
- [ ] Commands that were run by hand are pasted into this description, with their output
```
