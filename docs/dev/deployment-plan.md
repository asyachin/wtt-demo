# Deployment Plan

## How to Use This Plan

The work is split into 14 blocks. Each block is small enough to finish in one sitting and large enough to be worth a branch.

For every block:

1. Create the branch named in the block.
2. Write the tests first. Run them. They must fail. This is the **RED** state.
3. Commit the failing tests and push the branch. The CI run is expected to fail at this point. That failing run is the proof that the tests test something.
4. Write the implementation until the tests pass. This is the **GREEN** state.
5. Commit, push, and open a pull request into `dev`. When CI is green, auto-merge takes over.
6. Update the status of the block in [../roadmap.md](../roadmap.md) and write any documentation the block produces, in the same pull request.

Rules that apply to every block:

- A block is not finished until its tests pass in CI, not only on the laptop.
- A block never leaves a broken `dev` branch behind.
- A block never introduces a secret into Git.
- If a block turns out to need a decision, write an ADR in the same pull request. Do not decide silently.
- The branch is deleted after the merge.

The full branching and promotion model is in [git-workflow.md](git-workflow.md). The test layers and tools are in [testing-strategy.md](testing-strategy.md).

## Dependency Order

```
00 bootstrap
 └─ 01 images
     └─ 02 app contract (health, metrics, defects)
         └─ 03 CI pipeline
             └─ 04 image publishing
                 └─ 05 helm chart
                     └─ 06 terraform: network and EKS
                         └─ 07 terraform: platform add-ons
                             └─ 08 argo cd
                                 ├─ 09 secrets
                                 ├─ 10 observability
                                 └─ 11 data persistence and recovery
                                     └─ 12 security hardening
                                         └─ 13 release and demo readiness
```

Blocks 09, 10, and 11 can be done in any order once Block 08 is finished. Everything else is strictly sequential.

---

## Block 00 — Repository Bootstrap and Hygiene

**Branch:** `block/00-bootstrap`
**Depends on:** nothing
**Fixes defects:** D7, D8, D9

### Goal

Turn the directory into a real Git repository with a clean history, remove the traces of the previous project that affect correctness, and make sure no secret can ever be committed.

### Deliverables

| File | Purpose |
|---|---|
| `.gitignore` | Ignore build output, environment files, Terraform state, caches. **Written and verified.** |
| `.dockerignore`, `app/.dockerignore`, and one per service | Keep each build context small and free of secrets. **Written and verified.** |
| `.editorconfig` | Consistent line endings and indentation |
| `.gitattributes` | Force LF line endings, mark vendored files |
| `app/.env.template` | Rewritten: one key per line, no trailing comments, no credentials |
| `.github/workflows/secret-scan.yaml` | Gitleaks on every push |
| `.github/pull_request_template.md` | Checklist: tests, docs, ADR, no secrets |
| `tests/requirements.txt` | The Python test dependencies |
| `tests/conftest.py` | Shared fixtures and the pytest markers |
| `pyproject.toml` | Ruff and pytest configuration in one place |
| `LICENSE` | MIT |
| `docs/adr/0001-record-architecture-decisions.md` | The ADR process itself |

Manual steps, recorded in the pull request body:

- Delete the symlink `app/.env`. It points at the previous project's secret file.
- Delete the directory `app/worker/obj/`.
- Delete `ns.tmp`.
- Fix the two environment files in `/home/vmadmin/.secrets/portfolio/app/` so that every line is a `KEY=VALUE` pair. Replace the bare `eu-north-1` line with `AWS_REGION=eu-north-1`.
- Create the GitHub repository and push `main`, then create `dev` from `main`.
- Load the keys from `.env.dev` into a GitHub Actions environment named `dev`.

The ignore files are already written and verified. They are the real files, not a sketch:

| File | Context it applies to | Style |
|---|---|---|
| `.gitignore` | the whole repository | deny-list |
| `.dockerignore` | a build with context `.`, which nothing does. A safety net. | deny-list |
| `app/.dockerignore` | a build with context `app/`, which only the migration service may use | deny-list |
| `app/vote/.dockerignore` | `docker build app/vote` | allow-list |
| `app/result/.dockerignore` | `docker build app/result` | allow-list |
| `app/worker/.dockerignore` | `docker build app/worker` | allow-list |

Docker reads only the `.dockerignore` that sits in the context directory. A rule at the repository root does not apply to `app/vote`, which is why there are four of them rather than one.

The three service files are allow-lists: `*` first, then the few files the image needs added back. A deny-list silently ships anything nobody thought to exclude. An allow-list fails visibly instead, which is the right failure for a build. The file sets are tiny and stable, so the maintenance cost is a line per new file.

Four rules in `.gitignore` are worth knowing about, because each one is a trap that was hit or avoided deliberately:

| Rule | Why it is written that way |
|---|---|
| A bare `env/` is **not** listed | It would match `infra/terraform/env/`, which holds every Terraform root module. The first draft of this file had it, and it silently ignored all of the infrastructure code including the provider lock file. Found by running `git check-ignore`, not by reading. |
| `.terraform.lock.hcl` is **not** ignored | The provider lock file is committed on purpose, so that every apply resolves the same provider versions. |
| `/dist/` and `/build/` are anchored | Unanchored, they would match any directory with those names anywhere in the tree. |
| `bin/` and `obj/` are scoped to `app/worker/` | There is exactly one .NET project. A bare `bin/` or `obj/` is a generic name that could match something unrelated later. |

`terraform.tfvars` is committed, because it holds non-secret values such as the operator address allowlist, and `test_no_secret_in_terraform_tfvars` in Block 09 keeps it that way. Only `*secret*.tfvars`, `*secrets*.tfvars`, and `*.auto.tfvars` are ignored.

### RED

`tests/unit/test_repository_hygiene.py`, running without any container or network:

| Test | Asserts |
|---|---|
| `test_no_env_symlink` | `app/.env` does not exist |
| `test_gitignore_blocks_env_files` | `git check-ignore app/.env.dev` returns 0, and `git check-ignore app/.env.template` returns 1 |
| `test_gitignore_blocks_build_output` | `git check-ignore app/worker/obj/project.assets.json` returns 0 |
| `test_no_build_output_tracked` | `git ls-files` contains no path with `/obj/`, `/bin/`, or `node_modules/` |
| `test_infrastructure_code_is_not_ignored` | `git check-ignore` returns 1 for `infra/terraform/env/platform/main.tf`, `terraform.tfvars`, and `.terraform.lock.hcl`, and for `deploy/helm/wtt-vote/values-prod.yaml`. **An ignore file is only half tested if nothing checks what it must not match.** |
| `test_dockerignore_exists_per_build_context` | Every directory named as a build context in `docker-compose.yml` contains a `.dockerignore` |
| `test_service_dockerignores_are_allow_lists` | Each of the three service files starts with a `*` rule |
| `test_no_previous_project_references` | `git grep -i` finds no match for `ironhack`, `lilywalch`, `diogobarros`, `v2-lwinux`, or `wtt-campusone.click` in tracked files |
| `test_env_template_is_parseable` | Every non-empty, non-comment line in `app/.env.template` matches `^[A-Z][A-Z0-9_]*=.*$` and contains no ` #` |
| `test_env_template_has_no_credentials` | No line of `app/.env.template` contains a value for a key ending in `PASSWORD` or `TOKEN` |

All ten fail on the first run, because the repository is not a repository yet and the files do not exist.

`test_infrastructure_code_is_not_ignored` exists because of a real mistake. The first draft of `.gitignore` contained `env/` for Python virtual environments, which also matched `infra/terraform/env/` and silently ignored every Terraform root module. Reading the file did not catch it. Running `git check-ignore` against a list of paths that must stay tracked did.

### GREEN

Initialise the repository, write the files above, perform the manual deletions, and run the tests again.

### Done When

- `pytest tests/unit/test_repository_hygiene.py` passes.
- The Gitleaks workflow runs and reports no finding.
- `main` and `dev` both exist on GitHub.
- `git log` has no commit that ever contained a secret. If one slips in, start the history again. Do not try to rewrite it.

### Notes

The GitHub Actions environment named `dev` holds the values from `.env.dev`. These are development credentials for throwaway containers. They are not production secrets. Production secrets never touch GitHub; they go into AWS Secrets Manager in Block 09.

---

## Block 01 — Legacy Cleanup and Multi-Stage Images

**Branch:** `block/01-images`
**Depends on:** Block 00
**Fixes defects:** D6, D7, D10, D11, D12

### Goal

Three small images, each built in multiple stages, each running as a non-root user, each with pinned dependencies and standard metadata labels. Delete everything the target architecture does not use.

### Deliverables

| File | Change |
|---|---|
| `app/vote/Dockerfile` | Rewritten: `builder` stage installs into a virtual environment, `runtime` stage copies it, non-root user, `HEALTHCHECK` |
| `app/result/Dockerfile` | Rewritten as multi-stage: `deps` stage runs `npm ci --omit=dev`, `runtime` stage copies `node_modules`, non-root user. `nodemon` removed. |
| `app/worker/Dockerfile` | Kept multi-stage, now with a non-root user and `--no-restore` on publish |
| `app/vote/requirements.txt` | Every dependency pinned to an exact version |
| `app/result/package.json` | `stoppable` and `method-override` removed, `author` and `description` filled in |
| `app/result/server.js` | Duplicate `require('pg')` removed |
| `app/docker-compose.yml` | Rewritten: pinned image tags, `POSTGRES_DB` passed to the database, volume for Redis, explicit `env_file`, no Ironhack comment |
| `app/docker-compose.deploy.yml` | Deleted |
| `app/healthchecks/redis.sh` | `#!/bin/sh` with `set -eu`, no bash-only options |
| `docs/dev/images-and-tags.md` | Written |

Required labels on every image:

```
org.opencontainers.image.source
org.opencontainers.image.revision
org.opencontainers.image.created
org.opencontainers.image.title
org.opencontainers.image.licenses
```

### RED

`tests/unit/test_dockerfiles.py` reads the three Dockerfiles as text:

| Test | Asserts |
|---|---|
| `test_all_dockerfiles_are_multistage` | Each file has at least two `FROM ... AS` lines |
| `test_all_images_declare_non_root_user` | Each file has a `USER` instruction whose value is not `root` or `0` |
| `test_base_images_are_pinned_by_digest_or_exact_tag` | No `FROM` line uses `:latest` or a bare image name |
| `test_no_dev_tooling_in_runtime_stage` | The last stage of `result/Dockerfile` does not install `nodemon` |
| `test_required_labels_present` | All five labels appear in each Dockerfile |
| `test_python_requirements_are_pinned` | Every line of `requirements.txt` matches `^[A-Za-z0-9._-]+==[0-9]` |
| `test_deploy_compose_is_gone` | `app/docker-compose.deploy.yml` does not exist |

`tests/integration/test_image_properties.py` builds the images and inspects them. Marked `integration`, needs Docker:

| Test | Asserts |
|---|---|
| `test_image_runs_as_non_root` | `docker run --rm <image> id -u` is not `0` for `vote` and `result`, and `docker inspect` reports a non-root `User` for `worker` |
| `test_image_size_budget` | `vote` under 220 MB, `result` under 250 MB, `worker` under 230 MB |
| `test_no_package_manager_cache_in_image` | `/var/lib/apt/lists` and `/root/.npm` are empty or absent |
| `test_image_has_source_label` | `org.opencontainers.image.source` points at this repository |

### GREEN

Rewrite the three Dockerfiles, pin the dependencies, delete the unused files, and iterate until the size budgets are met.

### Done When

- Both test files pass.
- `docker compose --env-file .env.dev up` brings the whole stack to a healthy state, and a vote submitted in the browser appears on the result page.
- `git grep` finds no reference to the previous project. The Block 00 test already covers this and must still pass.
- `docs/dev/images-and-tags.md` explains the stage layout and the size budgets.

### Notes

The size budgets exist to stop image bloat from creeping back in. If a budget cannot be met for a real reason, change the number in the test in the same pull request and say why in the commit message. A budget that is quietly removed is a budget that never existed.

---

## Block 02 — Health, Metrics, and Application Defects

**Branch:** `block/02-app-contract`
**Depends on:** Block 01
**Fixes defects:** D1, D2, D3, D4, D5, D13

### Goal

Give every service the contract Kubernetes and Prometheus need, and fix the defects that make the application behave incorrectly or leak secrets. This is the block where the application becomes honest about its own state.

### The Contract

| Endpoint | Meaning | Must not |
|---|---|---|
| `GET /healthz` | The process is alive and can serve HTTP. Returns 200 with body `ok`. | Touch Redis or PostgreSQL. A dependency outage must not restart the pod. |
| `GET /readyz` | Every dependency this service needs is reachable right now. Returns 200 or 503 with a JSON body naming the failing dependency. | Be slow. Budget: 500 ms. |
| `GET /metrics` | Prometheus text format. | Require authentication inside the cluster. |

Per service:

| Service | Readiness checks | Metrics port | Library |
|---|---|---|---|
| `vote` | Redis `PING` | 80, same server | `prometheus-client` plus `prometheus-flask-exporter` |
| `result` | PostgreSQL `SELECT 1` | 80, same server | `prom-client` |
| `worker` | Redis `PING` and PostgreSQL `SELECT 1` | 9090, a small listener added for this purpose | `prometheus-net` |

Application metrics that must exist, beyond the defaults:

| Metric | Type | Service |
|---|---|---|
| `votes_submitted_total{option}` | counter | `vote` |
| `vote_queue_length` | gauge | `worker` |
| `votes_processed_total{option}` | counter | `worker` |
| `votes_failed_total{reason}` | counter | `worker` |
| `vote_processing_seconds` | histogram | `worker` |
| `result_query_seconds` | histogram | `result` |

`vote_queue_length` is the key metric. It is the queue depth between the web tier and the database tier, which makes it the one number that shows whether the system is keeping up. The alert in Block 10 is built on it.

### Deliverables

| File | Change |
|---|---|
| `app/vote/app.py` | `/healthz`, `/readyz`, `/metrics`, `secrets.token_hex(8)` for the voter identifier, counter for submitted votes, application factory so the module is importable in tests |
| `app/vote/templates/index.html` | All three content delivery network references replaced by local files |
| `app/vote/static/vendor/` | jQuery, the jQuery cookie plugin, and Font Awesome, vendored with their versions in the filenames |
| `app/result/server.js` | `/healthz`, `/readyz`, `/metrics`, the connection string no longer logged, query duration histogram |
| `app/worker/Program.cs` | Reads `DB_PORT` and `REDIS_PORT`, builds a complete connection string, connects to Redis by hostname, no password in the log, writes the vote after a reconnect, `ON CONFLICT (id) DO UPDATE`, metrics listener on 9090 |
| `app/db/migrations/001_votes.sql` | `CREATE TABLE IF NOT EXISTS votes (id VARCHAR(255) PRIMARY KEY, vote VARCHAR(255) NOT NULL)` plus an index on `vote` |
| `app/db/migrations/002_add_primary_key.sql` | Deduplicate existing rows, then add the primary key. Needed because the old table has duplicates. |
| `app/worker/Program.cs` | Schema creation removed. The migration now owns the schema. |
| `app/docker-compose.yml` | A `migrate` service that runs the migrations before the worker starts |

### RED

`tests/unit/test_vote_app.py`, no containers, using the Flask test client:

| Test | Asserts |
|---|---|
| `test_healthz_returns_200_without_redis` | With `REDIS_HOST` pointed at an unroutable address, `/healthz` is still 200 |
| `test_readyz_returns_503_without_redis` | Same conditions, `/readyz` is 503 and the body names `redis` |
| `test_metrics_exposes_vote_counter` | After one `POST /`, `/metrics` contains `votes_submitted_total` |
| `test_voter_id_is_16_hex_characters` | The `voter_id` cookie matches `^[0-9a-f]{16}$` |
| `test_page_has_no_external_resources` | The rendered HTML contains no `http://` and no `//cdn` reference |

`tests/integration/test_vote_flow.py`, against the Docker Compose stack, marked `integration`:

| Test | Asserts |
|---|---|
| `test_single_vote_reaches_database` | `POST /` with `vote=a`, then within 10 seconds the database has exactly one row |
| `test_revote_replaces_and_does_not_duplicate` | Two votes with the same `voter_id` cookie, different options. The database has exactly one row and it holds the second option. **This is the test that proves D1 is fixed.** |
| `test_vote_survives_database_restart` | Submit a vote, restart the `db` container, and the vote appears once the database is back. **This is the test that proves D2 is fixed.** |
| `test_result_reflects_counts` | After three votes, the `scores` payload from the result service matches the database |
| `test_readyz_turns_unhealthy_when_redis_stops` | Stop the `redis` container. `vote/readyz` becomes 503 within 10 seconds and `vote/healthz` stays 200. |
| `test_worker_exposes_queue_length` | Push 5 votes with the worker stopped, and `vote_queue_length` on the worker metrics port reports 5 |
| `test_no_password_in_any_log` | `docker compose logs` contains no occurrence of the `POSTGRES_PASSWORD` value. **This is the test that proves D3 is fixed.** |

### GREEN

Implement the changes service by service. `test_revote_replaces_and_does_not_duplicate` will need the migration, the primary key, and the `ON CONFLICT` write together. Do not try to make it pass with application logic alone.

### Done When

- Both test files pass.
- A manual vote on the local stack still works in a browser, including the "you voted" state, which was broken by D5.
- `docs/arch/application.md` is updated: every defect fixed in this block is marked as fixed with the block number.

### Notes

`test_no_password_in_any_log` is the kind of test most projects never write, and it is the reason the defect stays fixed. Keep it.

---

## Block 03 — Test Harness and CI Pipeline

**Branch:** `block/03-ci`
**Depends on:** Block 02

### Goal

Every check that a human runs locally runs automatically on every push, in the same way, with the same result. From this block onward, nothing merges without a green pipeline.

### Deliverables

| File | Purpose |
|---|---|
| `.github/workflows/ci.yaml` | The main pipeline |
| `.github/workflows/secret-scan.yaml` | Already exists from Block 00, now also runs on pull requests |
| `.hadolint.yaml` | Dockerfile lint rules |
| `.yamllint.yaml` | YAML lint rules |
| `Makefile` | `make lint`, `make test-unit`, `make test-integration`, `make scan`, `make ci`. The same commands locally and in CI. |
| `docs/dev/testing-strategy.md` | Written |
| `docs/dev/local-development.md` | Written |

Pipeline jobs, in order:

| Job | Runs | Fails the build |
|---|---|---|
| `lint` | `ruff check`, `ruff format --check`, `hadolint`, `yamllint`, `npm run lint` in `result`, `dotnet format --verify-no-changes` in `worker` | yes |
| `unit` | `pytest -m unit` with coverage | yes, and also below 70 percent coverage of `app/vote` |
| `build` | Build all three images with `docker buildx`, with the GitHub Actions cache | yes |
| `integration` | `docker compose up`, then `pytest -m integration` | yes |
| `scan` | Trivy on all three images, `--severity HIGH,CRITICAL`, `--exit-code 0`, plus `trivy config` on the Dockerfiles and the Compose file, SARIF uploaded to the GitHub security tab | no, by decision |
| `ci-complete` | A gate job that needs all of the above except `scan` | yes |

The `scan` job never fails the build. This is a conscious decision, recorded in [ADR 0012](../adr/0012-testing-strategy.md). A base image can gain a critical finding overnight with no fix available, and a pipeline that blocks on that teaches the team to bypass the pipeline. The findings are visible in the security tab and reviewed in Block 12 instead. Only one exception is hard: a finding in the application's own dependencies, as opposed to the base operating system, fails the `unit` job through `pip-audit` and `npm audit --omit=dev`.

### RED

| Test | Asserts |
|---|---|
| `tests/unit/test_ci_contract.py::test_workflow_exists` | `.github/workflows/ci.yaml` parses as YAML |
| `::test_all_required_jobs_present` | The job names above all exist |
| `::test_integration_job_uses_dev_environment` | The `integration` job declares `environment: dev` |
| `::test_scan_job_does_not_block` | The `scan` job passes `--exit-code 0` |
| `::test_gate_job_requires_every_blocking_job` | `ci-complete` lists every blocking job under `needs` |
| `::test_makefile_targets_exist` | `make -n lint test-unit test-integration scan ci` succeeds |
| `::test_no_hardcoded_secrets_in_workflows` | No workflow file contains a string that looks like a key, and every secret comes from `secrets.` or `vars.` |

These are tests about the pipeline rather than about the product. They are worth having because a pipeline that silently loses a job is worse than no pipeline.

### GREEN

Write the workflow and the Makefile until the contract tests pass, then push and confirm the real run is green.

### Done When

- The contract tests pass.
- A real push produces a green pipeline with all jobs visible.
- A deliberately broken test produces a red pipeline. Verify this once, by hand, and note it in the pull request. An untested gate is not a gate.
- The Trivy report is visible in the GitHub security tab.
- The total pipeline time is under 10 minutes. Record the actual number.

---

## Block 04 — Image Publishing and Auto-Merge

**Branch:** `block/04-publish`
**Depends on:** Block 03

### Goal

Every merge into `dev` produces, for each of the three services, one development image and one production image that carry the same tag. The tag makes it possible to say with certainty which development image a given production image came from.

### The Tag Scheme

```
<semver>-<utc timestamp>-g<short sha>

example: 0.3.0-20261014T120533Z-g1a2b3c4
```

| Part | Source | Why |
|---|---|---|
| `<semver>` | `VERSION` file at the repository root | Human-readable ordering |
| `<utc timestamp>` | `date -u +%Y%m%dT%H%M%SZ` at build time | Sorts correctly, and answers "when was this built" without an API call |
| `g<short sha>` | `git rev-parse --short=7 HEAD` | Ties the image back to one commit |

Each service produces two images with that identical tag:

| Image | Built from | Used by |
|---|---|---|
| `ghcr.io/asyachin/wtt-vote-dev:<tag>` | the `dev` stage of the Dockerfile | namespace `vote-dev` |
| `ghcr.io/asyachin/wtt-vote:<tag>` | the `runtime` stage of the Dockerfile | namespace `vote-prod` |

The same for `wtt-result` and `wtt-worker`. Nothing is ever tagged `latest`. The reasoning, and the trade-off that the two images are not bit-identical, is in [ADR 0006](../adr/0006-registry-and-image-tags.md) and [images-and-tags.md](images-and-tags.md).

### Deliverables

| File | Purpose |
|---|---|
| `VERSION` | The semantic version, one line |
| `.github/workflows/publish.yaml` | Builds, scans, signs, pushes, and writes the tag into `values-dev.yaml` |
| `.github/workflows/auto-merge.yaml` | Enables auto-merge on a pull request into `dev` once CI is green |
| `scripts/image-tag.sh` | Computes the tag. Used by CI and available locally, so the two cannot drift. |

The `publish` workflow:

1. Computes the tag once and passes it to every later step. It must never be computed twice, or the timestamps will differ.
2. Builds and pushes both targets for all three services with `docker buildx`, for `linux/amd64` only.
3. Runs Trivy on the production images and uploads the report.
4. Signs the production images with `cosign` in keyless mode, using the GitHub Actions identity.
5. Writes an SBOM for each production image and attaches it to the GitHub release draft.
6. Commits the new tag into `deploy/helm/wtt-vote/values-dev.yaml` on branch `dev`, with `[skip ci]` in the message to avoid a loop.
7. Writes a job summary table with the six image references and the shared tag.

Auto-merge rules on `dev`:

- Branch protection requires the `ci-complete` check.
- `gh pr merge --auto --squash` is enabled by the workflow.
- A pull request that changes anything under `infra/` or `deploy/argocd/` is excluded from auto-merge and needs a manual merge. Infrastructure changes are not merged by a robot.

### RED

| Test | Asserts |
|---|---|
| `tests/unit/test_image_tag.py::test_tag_format` | `scripts/image-tag.sh` output matches `^\d+\.\d+\.\d+-\d{8}T\d{6}Z-g[0-9a-f]{7}$` |
| `::test_tag_is_stable_within_one_invocation` | The script prints the same value twice when called with a fixed timestamp input |
| `::test_version_file_is_valid_semver` | `VERSION` parses |
| `tests/unit/test_publish_workflow.py::test_builds_both_targets` | The workflow builds both `dev` and `runtime` targets for all three services |
| `::test_dev_and_prod_share_one_tag` | Both image references in the workflow use the same tag expression |
| `::test_no_latest_tag` | No workflow file contains `:latest` |
| `::test_values_dev_is_updated` | The workflow has a step that writes the tag into `values-dev.yaml` |
| `::test_bot_commit_skips_ci` | That step's commit message contains `[skip ci]` |
| `::test_infra_changes_excluded_from_auto_merge` | The auto-merge workflow has a path filter that excludes `infra/**` |
| `tests/integration/test_published_images.py::test_tag_pair_exists_in_registry` | For the latest tag, both the `-dev` and the plain image exist in GHCR and can be pulled. Runs after the first real publish. |

### GREEN

Write the two workflows and the script. Then run them for real. A publishing pipeline cannot be proven by unit tests alone, so the integration test against GHCR is required before the block closes.

### Done When

- All unit tests pass and the registry test passes against a real tag.
- GHCR shows six images with one shared tag.
- `cosign verify` succeeds against one production image. Record the command in [images-and-tags.md](images-and-tags.md).
- A pull request into `dev` merges itself when CI is green, and a pull request touching `infra/` does not.

### Notes

Blocks 05 onward need `values-dev.yaml` to exist, which does not happen until Block 05. Write the step that updates it in this block, and allow it to be skipped when the file is missing. Remove that allowance at the end of Block 05 and add a test that the step now really runs.

---

## Block 05 — Helm Chart

**Branch:** `block/05-helm`
**Depends on:** Block 04

### Goal

One chart that describes the whole application, with two value files that differ only in what genuinely differs between environments. Validated locally before any AWS spend.

### Deliverables

```
deploy/helm/wtt-vote/
├── Chart.yaml
├── values.yaml              defaults, and documentation of every key
├── values-dev.yaml          the dev overlay
├── values-prod.yaml         the prod overlay
├── templates/
│   ├── _helpers.tpl
│   ├── vote-deployment.yaml
│   ├── vote-service.yaml
│   ├── result-deployment.yaml
│   ├── result-service.yaml
│   ├── worker-deployment.yaml
│   ├── worker-service.yaml          metrics port only
│   ├── postgres-statefulset.yaml
│   ├── postgres-service.yaml
│   ├── redis-statefulset.yaml
│   ├── redis-service.yaml
│   ├── migration-job.yaml           a Helm pre-upgrade hook
│   ├── httproute.yaml               Gateway API, attaches to the platform Gateway
│   ├── referencegrant.yaml          only if a route crosses a namespace
│   ├── servicemonitor.yaml
│   ├── pdb.yaml
│   ├── networkpolicy.yaml
│   ├── resourcequota.yaml
│   └── NOTES.txt
└── tests/
    └── ...                   helm unittest cases
```

Rules the chart must follow:

- No image tag in `values.yaml`. The tag lives only in the environment overlay, because that is what CI writes and what promotion moves.
- Every container sets `resources.requests` and `resources.limits`.
- Every container sets `securityContext` with `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, and `capabilities.drop: [ALL]`.
- Every workload sets `livenessProbe` on `/healthz` and `readinessProbe` on `/readyz`. The worker uses port 9090.
- Database credentials come from a Kubernetes Secret reference, never from a value. In this block the Secret is created by hand; Block 09 replaces it with External Secrets.
- The migration runs as a Helm `pre-upgrade,pre-install` hook with `hook-weight: -5`, so the schema is ready before the worker starts.
- Stateless services get two replicas in production and a PodDisruptionBudget with `minAvailable: 1`.
- `postgres` and `redis` are StatefulSets with `volumeClaimTemplates`, storage class `gp3`.
- Routing is expressed as `HTTPRoute` objects, not as an `Ingress`. The chart owns its routes and nothing else about the edge. The `GatewayClass` and the `Gateway` belong to the platform and are installed by Terraform in Block 07, which is the separation of responsibility that [ADR 0015](../adr/0015-traefik-gateway-api.md) exists for.
- The chart must contain no vendor annotation on any routing object. If something cannot be expressed in the Gateway API, that is a finding worth recording, not a reason to reach for an annotation.
- In `vote-prod` the chart creates two routes on the HTTPS listener: `PathPrefix /` to `vote` and `PathPrefix /result` to `result`. The `/result` prefix is what covers `/result/socket.io`, so it must not be narrowed.
- The `ResponseHeaderModifier` filter on the routes sets `Strict-Transport-Security`, `X-Content-Type-Options`, and `X-Frame-Options`. Those headers are now the chart's job, not a load balancer attribute outside the cluster.
- In `vote-dev` the chart creates no route at all, because development has no public hostname. The value `httpRoute.enabled` controls it, and it is one of the keys permitted to differ between the two environments.

### RED

`tests/unit/test_helm_chart.py` runs `helm template` and parses the output. No cluster needed:

| Test | Asserts |
|---|---|
| `test_chart_lints` | `helm lint` exits 0 for both value files |
| `test_manifests_are_valid` | `kubeconform` with the strict schema passes for both renderings |
| `test_every_container_has_probes` | Every container in the output has both a liveness and a readiness probe |
| `test_every_container_has_resource_limits` | No container is missing requests or limits |
| `test_every_container_runs_as_non_root` | `runAsNonRoot` is true everywhere |
| `test_no_plaintext_password_in_manifests` | No rendered manifest has a password as a literal value; all come from `secretKeyRef` |
| `test_no_image_tag_in_default_values` | `values.yaml` has no `tag:` with a value |
| `test_prod_has_two_replicas` | `vote` and `result` have `replicas: 2` under `values-prod.yaml` |
| `test_route_covers_result_socketio` | An `HTTPRoute` rule matches `PathPrefix /result`, so `/result/socket.io` is covered |
| `test_no_vendor_annotation_on_routes` | No `HTTPRoute` carries a `traefik.io/` or `alb.ingress.kubernetes.io/` annotation |
| `test_response_header_filter_sets_security_headers` | The route filter sets all three security headers |
| `test_dev_creates_no_route` | Rendering with `values-dev.yaml` produces no `HTTPRoute` |
| `test_migration_is_a_pre_upgrade_hook` | The Job carries the right Helm hook annotations |
| `test_dev_and_prod_differ_only_in_allowed_keys` | Diffing the two renderings shows differences only in namespace, replica counts, resource values, image reference, route presence, and secret path. Anything else is accidental drift. |

`tests/platform/test_chart_on_kind.py`, marked `platform`, runs against a local `kind` cluster in CI. This is where the Traefik decision pays for itself: the whole routing layer is exercised here rather than first on live AWS in Block 07.

| Test | Asserts |
|---|---|
| `test_chart_installs` | `helm install` reaches a ready state within 180 seconds |
| `test_full_vote_flow_in_cluster` | Port-forward the `vote` service, submit a vote, and read it back through the `result` service |
| `test_migration_job_completed` | The migration Job has a successful completion |
| `test_upgrade_is_clean` | `helm upgrade` with a new tag completes with no pod in `CrashLoopBackOff` |
| `test_gateway_is_accepted` | The `Gateway` reports both `Accepted` and `Programmed` |
| `test_httproute_is_attached` | Every `HTTPRoute` reports `ResolvedRefs` and a parent that accepted it |
| `test_routing_matches_paths` | Through the Traefik service: `/` returns the voting page and `/result` returns the result page |
| `test_websocket_upgrade_succeeds` | A websocket handshake on `/result/socket.io` returns 101. **The one routing detail of this application that is easy to get wrong, now checked on every push.** |
| `test_http_redirects_to_https_in_kind` | The `RequestRedirect` filter on the HTTP listener answers 301 with an `https` location |
| `test_allowed_routes_restricts_namespaces` | An `HTTPRoute` created in an unlabelled namespace is rejected with `NotAllowedByListeners` |
| `test_experimental_channel_disabled` | The Traefik values set `experimentalChannel: false` |

Two tests in this block are worth more than the rest.

`test_dev_and_prod_differ_only_in_allowed_keys` makes environment drift impossible to add by accident, which is the most common cause of "it worked in dev".

`test_allowed_routes_restricts_namespaces` is the one that proves the separation of responsibility is enforced by the API server rather than by convention. Without it, the Gateway API is just a different syntax for an `Ingress`.

### GREEN

Write the chart. Install `kind`, which is not on this machine yet. The `kind` cluster needs the Gateway API Standard channel CRDs and Traefik installed before the chart, so write a `tests/platform/kind-setup.sh` that does it with the same pinned versions Terraform will use in Block 07. If the two drift, the `kind` tests stop proving anything about production.

Set `experimentalChannel: false` explicitly. Setting it to true without the Experimental CRDs installed makes the Traefik Gateway provider serve no resource at all, so unrelated and previously working routes start returning 404, and the only symptom is a repeating reflector error in the Traefik log.

### Done When

- All unit tests and all `kind` tests pass, in CI.
- The CI pipeline now has a `chart` job that includes the routing tests.
- The Gateway API CRD version and the Traefik chart version are pinned in one place and are the same values Block 07 will use on EKS.
- The allowance added in Block 04 for the missing `values-dev.yaml` is removed, and the publish workflow really writes the tag.

---

## Block 06 — Terraform: Network and EKS

**Branch:** `block/06-eks`
**Depends on:** Block 05
**This block spends money. Read the cost table in [../roadmap.md](../roadmap.md) first.**

### Goal

One reproducible command creates the network and an empty, reachable EKS cluster. Nothing is created by hand in the console, ever.

### Deliverables

```
infra/terraform/
├── bootstrap/                   state bucket and lock table, local state, run once
│   └── main.tf
├── modules/
│   ├── network/                 VPC, subnets, NAT, route tables, subnet tags for EKS
│   └── eks/                     cluster, OIDC provider, managed node group, add-ons
└── env/platform/
    ├── backend.tf               S3 backend, DynamoDB lock
    ├── main.tf
    ├── variables.tf
    ├── outputs.tf
    ├── versions.tf              provider version constraints, pinned
    └── terraform.tfvars         non-secret values only
```

Required outputs from `env/platform`, because later blocks read them:

```
cluster_name
cluster_endpoint
cluster_oidc_issuer_url
vpc_id
private_subnet_ids
public_subnet_ids
node_security_group_id
region
```

Subnet tagging matters and is easy to get wrong. The load balancer controller will not find the subnets without it:

| Subnet | Tags |
|---|---|
| public | `kubernetes.io/role/elb = 1`, `kubernetes.io/cluster/<name> = shared` |
| private | `kubernetes.io/role/internal-elb = 1`, `kubernetes.io/cluster/<name> = shared` |

Other settings:

- Kubernetes 1.31 or later. Pin the exact version in a variable.
- The cluster endpoint is public, restricted to the operator's IP range, and also private. Record the allowed range in `terraform.tfvars`.
- Control plane logging on for `api`, `audit`, and `authenticator`.
- Node group: 2 desired, 1 minimum, 4 maximum, `t3.small`, Spot, Amazon Linux 2023, in the private subnets.
- A second node group definition for On-Demand capacity, with 0 desired, kept as a documented fallback if Spot capacity disappears during the demonstration.
- EKS add-ons managed by Terraform: `vpc-cni`, `coredns`, `kube-proxy`, `aws-ebs-csi-driver`, each with an explicit version.
- `gp3` set as the default storage class, and the `gp2` class removed as default.

### RED

`tests/platform/test_terraform_static.py`, no AWS credentials needed:

| Test | Asserts |
|---|---|
| `test_terraform_fmt` | `terraform fmt -check -recursive` is clean |
| `test_terraform_validate` | `terraform validate` passes in every module |
| `test_tflint` | `tflint` reports no error |
| `test_checkov` | `checkov` reports no finding above medium, or the finding is listed with a written reason in `infra/terraform/.checkov.yaml` |
| `test_no_hardcoded_account_or_credentials` | No `.tf` file contains an AWS account identifier, an access key, or a secret |
| `test_remote_backend_configured` | `env/platform/backend.tf` uses S3 and a DynamoDB lock table |
| `test_provider_versions_pinned` | Every provider has a `~>` or exact constraint |
| `test_required_outputs_declared` | All eight outputs above exist in `outputs.tf` |
| `test_subnet_tags_for_load_balancer` | The network module sets all four tag pairs |

`tests/platform/test_eks_cluster.py`, marked `platform`, run by hand after `terraform apply`:

| Test | Asserts |
|---|---|
| `test_cluster_is_active` | `boto3` reports the cluster status as `ACTIVE` |
| `test_nodes_are_ready` | The Kubernetes API lists 2 nodes in `Ready` |
| `test_nodes_are_in_private_subnets` | No node has a public IP address |
| `test_oidc_provider_exists` | An IAM OIDC provider matches the cluster issuer |
| `test_gp3_is_default_storage_class` | Exactly one default storage class exists and it is `gp3` |
| `test_control_plane_logging_enabled` | All three log types are on |
| `test_cluster_endpoint_is_restricted` | Public access is limited to a non-empty, non-`0.0.0.0/0` list |
| `test_ebs_csi_can_provision` | A test PersistentVolumeClaim binds within 90 seconds, and is then deleted |

### GREEN

Run `bootstrap` once with local state, migrate it to S3, then `terraform apply` in `env/platform`. Expect 15 to 20 minutes for the first apply.

### Done When

- The static tests pass in CI, in a new `infra-validate` job that runs on every pull request touching `infra/`.
- The cluster tests pass against the real cluster.
- `terraform plan` immediately after a successful apply shows no change. A plan that is never empty means the configuration does not describe reality.
- A teardown procedure is written in [../ops/runbooks.md](../ops/runbooks.md) and has been read end to end, even though it is not run yet.
- The cost table in [../roadmap.md](../roadmap.md) is updated with the first real figures from Cost Explorer after 24 hours.

### Notes

The `infra-validate` job runs only the static tests. The `platform` tests need credentials for a real account and are run by hand, with the command recorded in the pull request. Giving a CI robot the right to apply infrastructure is a separate decision that this project does not need.

---

## Block 07 — Terraform: Platform Add-Ons

**Branch:** `block/07-addons`
**Depends on:** Block 06

### Goal

The cluster can now accept traffic from the internet, publish its own DNS records, present a valid certificate, mount volumes, and read secrets from AWS. Everything an application needs before the application arrives.

### Deliverables

| Component | Installed how | IAM |
|---|---|---|
| Gateway API CRDs, Standard channel, version pinned | `kubectl` apply through Terraform, before anything that needs them | none |
| Traefik v3, with `GatewayClass` and the platform `Gateway` | Helm, by Terraform | none |
| cert-manager, with two `ClusterIssuer` objects | Helm, by Terraform | IRSA role limited to `route53:ChangeResourceRecordSets` on the `syachin.de` hosted zone |
| ExternalDNS, source `gateway-httproute` | Helm, by Terraform | IRSA role limited to the same hosted zone |
| External Secrets Operator | Helm, by Terraform | IRSA role limited to `secretsmanager:GetSecretValue` on `/wtt-demo/*` |
| Metrics Server | Helm, by Terraform | none |
| Namespaces `vote-dev`, `vote-prod`, `observability`, `external-secrets`, `traefik`, `cert-manager` | Terraform | labelled with the `restricted` Pod Security Standard from the start, and with the gateway attachment label where a route is allowed |

New module: `infra/terraform/modules/platform/`. New outputs: `gateway_name`, `gateway_namespace`, `traefik_nlb_hostname`, `cert_manager_role_arn`, `external_dns_role_arn`, `external_secrets_role_arn`.

Ordering matters and is not negotiable:

1. Gateway API CRDs.
2. cert-manager, plus the two issuers, plus the `Certificate` object.
3. Traefik, which cannot serve its HTTPS listener until the certificate `Secret` exists.
4. The `Gateway`, with `allowedRoutes` selecting namespaces by label.
5. ExternalDNS, which reads `HTTPRoute` objects.

Settings that each cost an afternoon if missed:

- **Two Traefik entrypoints**, `8000` and `8443`. The NLB maps port 80 to 8000 and port 443 to 8443. The `RequestRedirect` filter lives only on the HTTP listener. A single entrypoint cannot distinguish the two schemes, because the NLB works at layer 4 and adds no `X-Forwarded-Proto`, so the redirect would loop.
- **Proxy Protocol v2** on the NLB target group and on both Traefik entrypoints, enabled in the same change. One side alone breaks all traffic. Without it, every log line and every future rate limit sees the NLB address instead of the client.
- **`experimentalChannel: false`**, explicitly. True without the Experimental CRDs stops the Gateway provider from serving any resource at all, and the symptom is unrelated routes returning 404 with only a repeating reflector error in the log.
- **The staging issuer first.** Point the real `Certificate` at `letsencrypt-staging` until the solver is proven, then switch to `letsencrypt-prod`. Let's Encrypt allows 5 duplicate certificates per week, and a debugging session exhausts that in an afternoon, after which the project waits a week.
- **DNS-01, not HTTP-01.** It produces the wildcard and works before any traffic reaches the cluster.

Every IRSA policy is written by hand and scoped. No `*` on resources and no managed policy that grants more than the component needs. This is the cheapest place in the whole project to demonstrate least privilege, and the easiest place to get it wrong. Note that two components now write into the same hosted zone, cert-manager for TXT challenge records and ExternalDNS for the A records, so both policies are scoped to that one zone and neither is given a wildcard.

### RED

Static tests, added to `tests/platform/test_terraform_static.py`:

| Test | Asserts |
|---|---|
| `test_no_wildcard_iam_resources` | No IAM policy document in any module has `Resource = "*"` unless the action genuinely requires it and the exception is listed in `infra/terraform/.iam-exceptions.yaml` with a reason |
| `test_external_dns_scoped_to_one_zone` | The ExternalDNS policy names the hosted zone identifier, not `*` |
| `test_cert_manager_scoped_to_one_zone` | The cert-manager policy names the same hosted zone identifier, not `*` |
| `test_external_secrets_scoped_to_prefix` | The policy restricts to the `arn:aws:secretsmanager:...:secret:/wtt-demo/*` prefix |
| `test_namespaces_have_pod_security_labels` | All six namespaces carry `pod-security.kubernetes.io/enforce: restricted` |
| `test_gateway_api_crd_version_pinned` | The CRD manifest URL in Terraform names an exact Gateway API version, and it is the same version `tests/platform/kind-setup.sh` uses |
| `test_traefik_chart_version_pinned` | The Helm release pins an exact chart version, matching the `kind` setup |
| `test_two_entrypoints_configured` | The Traefik values define `8000` and `8443`, and the Service maps 80 and 443 to them respectively |
| `test_proxy_protocol_enabled_on_both_sides` | The Service annotation and the entrypoint `proxyProtocol` setting are both present |

`tests/platform/test_platform_addons.py`, marked `platform`:

| Test | Asserts |
|---|---|
| `test_traefik_is_running` | Both replicas ready, and spread across the two nodes |
| `test_gateway_is_programmed` | The platform `Gateway` reports `Accepted` and `Programmed`, and its address is the NLB hostname |
| `test_nlb_is_provisioned` | `boto3` finds one internet-facing NLB whose target group is healthy |
| `test_cert_manager_is_healthy` | The controller, the webhook, and the cainjector are all ready |
| `test_staging_certificate_issues` | A throwaway `Certificate` against `letsencrypt-staging` reaches `Ready` within 300 seconds, which proves the DNS-01 solver before any production quota is spent |
| `test_production_certificate_is_ready` | The real `Certificate` reports `Ready`, with both names in `dnsNames` |
| `test_cert_manager_iam_is_scoped` | A record write outside the `syachin.de` hosted zone is denied |
| `test_external_dns_is_running` | Ready, and configured with source `gateway-httproute` |
| `test_external_secrets_crds_installed` | `ExternalSecret` and `ClusterSecretStore` are registered |
| `test_sample_route_answers_over_https` | Apply a throwaway `HTTPRoute` with an `echo` backend on a throwaway host; `https://` answers 200 within 180 seconds |
| `test_sample_route_creates_a_dns_record` | ExternalDNS creates the record in Route 53 within 180 seconds |
| `test_served_certificate_is_trusted` | The handshake is accepted by a standard trust store and the issuer is Let's Encrypt production, not the staging authority. **A staging certificate left in place is the most likely way to ship a browser warning.** |
| `test_proxy_protocol_passes_client_ip` | The Traefik access log for the throwaway request shows the real client address, not an NLB address |
| `test_throwaway_objects_cleaned_up` | After deletion, the DNS record is gone within 300 seconds and the NLB still exists, because it belongs to the Traefik Service and not to the route |

The throwaway route test is the one that matters. It proves the whole edge path, from DNS through the NLB and Traefik to a pod, before the real application depends on it. Debugging that path for the first time while also debugging the application is how a day gets lost.

Note what changed from the superseded design: the NLB is created by the Traefik `Service`, not by a route. Deleting a route no longer removes a load balancer, which is better for correctness and changes the teardown order. Both are reflected in the runbook.

### GREEN

Write the module in the order listed above and apply step by step rather than all at once. The usual failures are a cert-manager `ClusterIssuer` whose service account annotation does not match the IRSA trust policy, a `Gateway` whose `allowedRoutes` label selector does not match the namespace labels, and Proxy Protocol enabled on one side only.

Keep the real `Certificate` on the staging issuer until `test_staging_certificate_issues` passes. Switch to production once, and only once.

### Done When

- Static tests pass in CI.
- All fourteen platform tests pass.
- `terraform plan` is empty.
- The throwaway route and its DNS record are deleted and confirmed gone.
- The served certificate is from Let's Encrypt production, confirmed by `test_served_certificate_is_trusted`.
- The Gateway API CRD version and the Traefik chart version are identical in Terraform and in the `kind` setup script. If they drift, the Block 05 tests stop saying anything about production.

---

## Block 08 — Argo CD and GitOps Bootstrap

**Branch:** `block/08-argocd`
**Depends on:** Block 07

### Goal

The cluster state is driven by Git. Terraform installs Argo CD and nothing else. From then on, every object in the cluster comes from a commit.

### Deliverables

| File | Purpose |
|---|---|
| `infra/terraform/modules/platform/argocd.tf` | Installs Argo CD by Helm, with declarative configuration and the admin password from AWS Secrets Manager |
| `deploy/argocd/projects/wtt-demo.yaml` | An `AppProject` that limits which repositories, namespaces, and resource kinds are allowed |
| `deploy/argocd/apps/root.yaml` | The app-of-apps |
| `deploy/argocd/apps/vote-dev.yaml` | Tracks branch `dev`, values `values-dev.yaml`, namespace `vote-dev` |
| `deploy/argocd/apps/vote-prod.yaml` | Tracks branch `main`, values `values-prod.yaml`, namespace `vote-prod` |
| `deploy/argocd/apps/observability.yaml` | Placeholder, filled in Block 10 |
| `deploy/argocd/apps/external-secrets-config.yaml` | Placeholder, filled in Block 09 |
| `docs/ops/runbooks.md` | The Argo CD sections: force a sync, read a diff, roll back, recover the admin password |

Settings:

- Both applications use `syncPolicy.automated` with `prune: true` and `selfHeal: true`. Manual changes in the cluster are reverted. That is the point.
- `ServerSideApply` is on, to avoid annotation size limits on larger manifests.
- The `AppProject` restricts destinations to the two namespaces and the observability namespace, and restricts sources to this repository only.
- Argo CD manages itself through the app-of-apps after the initial Terraform install, so that its own configuration is also in Git.
- The Argo CD user interface is not published. Access is by `kubectl port-forward`. One public surface is enough.

### RED

`tests/unit/test_argocd_manifests.py`, no cluster:

| Test | Asserts |
|---|---|
| `test_manifests_parse` | Every file under `deploy/argocd/` is valid YAML with the expected `kind` |
| `test_dev_app_tracks_dev_branch` | `vote-dev` has `targetRevision: dev` |
| `test_prod_app_tracks_main_branch` | `vote-prod` has `targetRevision: main` |
| `test_both_apps_self_heal` | `prune` and `selfHeal` are true in both |
| `test_project_restricts_destinations` | The `AppProject` does not allow `*` as a namespace |
| `test_project_restricts_source_repos` | Only this repository is listed |
| `test_no_secret_in_argocd_manifests` | No `Secret` object with literal data under `deploy/argocd/` |

`tests/platform/test_argocd.py`, marked `platform`:

| Test | Asserts |
|---|---|
| `test_argocd_is_healthy` | Every Argo CD component is ready |
| `test_root_app_is_synced` | The app-of-apps reports `Synced` and `Healthy` |
| `test_both_environments_synced` | `vote-dev` and `vote-prod` both report `Synced` and `Healthy` |
| `test_self_heal_reverts_a_manual_change` | Scale the `vote` deployment to 5 with `kubectl`. Within 180 seconds it is back to the value in Git. **This is the test that proves GitOps is real and not decorative.** |
| `test_prune_removes_a_deleted_object` | Add a ConfigMap to Git, sync, remove it from Git, and it disappears from the cluster |
| `test_rollback_by_revert` | Commit a bad image tag to `dev`, confirm the rollout stalls, revert the commit, and confirm recovery without any manual `kubectl` |

### GREEN

Install Argo CD with Terraform, commit the application manifests, and let it converge. `test_rollback_by_revert` needs a real bad tag; use a tag that does not exist in GHCR so the pods go to `ImagePullBackOff` rather than running incorrect code.

### Done When

- All tests pass.
- Both namespaces run the application, with the dev images in `vote-dev` and the prod images in `vote-prod`.
- `https://wtt-demo.syachin.de/` serves the voting page over valid TLS, and `/result` shows the live count.
- The rollback procedure in [../ops/runbooks.md](../ops/runbooks.md) is written from the actual experience of running `test_rollback_by_revert`, not from memory.

---

## Block 09 — Secrets Management

**Branch:** `block/09-secrets`
**Depends on:** Block 08

### Goal

No secret exists in Git, in a Helm value, in a container image, or in a Terraform variable file. Every secret has one home, and a pod receives it through a defined path.

### The Secret Map

| Secret | Home | Reaches a pod by | Rotation |
|---|---|---|---|
| PostgreSQL password, prod | AWS Secrets Manager, `/wtt-demo/prod/postgres` | External Secrets, into Secret `postgres-credentials` in `vote-prod` | Manual, procedure in the runbook |
| PostgreSQL password, dev | AWS Secrets Manager, `/wtt-demo/dev/postgres` | Same, into `vote-dev` | Manual |
| Grafana admin password | AWS Secrets Manager, `/wtt-demo/prod/grafana` | External Secrets, into the observability namespace | Manual |
| Grafana read-only API token | AWS Secrets Manager, `/wtt-demo/prod/grafana-reader` | Created once, handed out to reviewers | Revoke and recreate |
| Argo CD admin password | AWS Secrets Manager, `/wtt-demo/prod/argocd` | Read by Terraform at install time | Manual |
| Backup bucket access | none | IRSA role on the backup service account. There is no credential to store. | not applicable |
| GHCR pull access | none | The packages are public. No pull secret exists. | not applicable |
| Test credentials for CI | GitHub Actions environment `dev` | Environment variables in the `integration` job | Replace when the values change |

Two homes, by design, and the boundary is sharp: GitHub Actions holds only throwaway credentials for containers that live for the length of a pipeline run. AWS Secrets Manager holds everything a running environment uses. A GitHub compromise must not expose a running environment. See [ADR 0007](../adr/0007-secrets-management.md).

### Deliverables

| File | Purpose |
|---|---|
| `infra/terraform/modules/platform/secrets.tf` | Creates the Secrets Manager entries with a generated value and `ignore_changes` on the value, so a rotation is never undone by an apply |
| `deploy/helm/wtt-vote/templates/externalsecret.yaml` | One `ExternalSecret` per environment |
| `deploy/argocd/apps/external-secrets-config.yaml` | The `ClusterSecretStore` |
| `docs/ops/secrets.md` | Written: the table above, plus the rotation procedure for each row |

### RED

| Test | Asserts |
|---|---|
| `tests/unit/test_no_secrets_in_repo.py::test_gitleaks_clean` | `gitleaks detect` on the full history reports nothing |
| `::test_no_secret_literal_in_helm_values` | No value file has a key ending in `PASSWORD`, `SECRET`, or `TOKEN` with a non-empty value |
| `::test_no_secret_in_terraform_tfvars` | Same for every `.tfvars` file |
| `::test_all_secret_env_vars_use_secret_key_ref` | In every rendered manifest, each environment variable whose name suggests a secret comes from `secretKeyRef` |
| `tests/platform/test_secrets_delivery.py::test_external_secret_is_ready` | Every `ExternalSecret` reports `SecretSynced` |
| `::test_pod_can_read_the_password` | The `result` pod's environment contains a password that matches the value in Secrets Manager |
| `::test_password_not_in_pod_logs` | `kubectl logs` for all three services contains no occurrence of the password. The cluster version of the Block 02 test. |
| `::test_rotation_propagates` | Change the value in Secrets Manager. Within the refresh interval plus a restart, the pod uses the new value and the application still works. **This is the test that proves the rotation procedure in the runbook is correct.** |
| `::test_irsa_is_scoped` | Using the External Secrets role, an attempt to read a secret outside `/wtt-demo/*` is denied |

### GREEN

Create the secrets, write the `ClusterSecretStore` and the `ExternalSecret` templates, replace the hand-made Secret from Block 05, and run the rotation test for real.

### Done When

- All tests pass.
- No hand-made Kubernetes Secret remains. `kubectl get secret -o yaml` shows every application secret with the `external-secrets` owner annotation.
- The rotation procedure in `docs/ops/secrets.md` was followed once, by hand, and the time it took is recorded.

---

## Block 10 — Observability

**Branch:** `block/10-observability`
**Depends on:** Block 08

### Goal

A question about the system can be answered from a dashboard or a query, not from guessing. A failure produces an alert before a user notices it. A reviewer can read the metrics over HTTP with a token.

### Deliverables

| File | Purpose |
|---|---|
| `deploy/argocd/apps/observability.yaml` | Installs `kube-prometheus-stack` |
| `deploy/observability/values.yaml` | Chart values: retention, storage, resource limits |
| `deploy/observability/httproute.yaml` | The Grafana route, attaching to the platform `Gateway` |
| `deploy/observability/rules/platform.yaml` | `PrometheusRule` for the gateway and certificate alerts |
| `deploy/observability/dashboards/application.json` | The application dashboard, provisioned as a ConfigMap |
| `deploy/observability/dashboards/platform.json` | Cluster and node dashboard, including the Traefik request rate, latency, and status codes, and the certificate expiry countdown |
| `deploy/observability/rules/application.yaml` | `PrometheusRule` with the alerts below |
| `docs/ops/observability.md` | Written: how to query, what each alert means, and the first step for each one |

Settings:

- Prometheus retention: 7 days, on a 20 GiB gp3 volume. Enough for a demonstration, and the number is a conscious choice rather than a default.
- Grafana is published at `grafana.wtt-demo.syachin.de`, by an `HTTPRoute` in the `observability` namespace attaching to the same platform `Gateway` as the application. Nothing else changes about the exposure design.
- Prometheus is **not** published directly. Its query API is reachable through the Grafana data source proxy, so there is one authentication system instead of two. The reasoning is in [ADR 0009](../adr/0009-observability.md).

Read-only API access for a reviewer:

```
# Query any metric through Grafana, with a read-only service account token
curl -H "Authorization: Bearer <token>" \
  "https://grafana.wtt-demo.syachin.de/api/datasources/proxy/uid/prometheus/api/v1/query?query=vote_queue_length"

# Grafana's own health endpoint, no token needed
curl https://grafana.wtt-demo.syachin.de/api/health
```

Alerts, with a reason for each one:

| Alert | Condition | Severity | Why it exists |
|---|---|---|---|
| `VoteServiceDown` | `up{job="vote"} == 0` for 2 minutes | critical | The demonstration is offline |
| `ResultServiceDown` | `up{job="result"} == 0` for 2 minutes | critical | The same |
| `WorkerNotProcessing` | `vote_queue_length > 50` for 5 minutes | critical | The queue is growing, so votes are not reaching the database. The clearest signal that the pipeline is broken. |
| `VoteErrorRateHigh` | 5xx rate above 5 percent for 5 minutes | warning | Something is failing without crashing |
| `PostgresDown` | `up{job="postgres"} == 0` for 1 minute | critical | The system of record is gone |
| `PostgresDiskFillingUp` | Projected to fill within 24 hours | warning | Prevents an outage rather than reporting one |
| `BackupJobFailed` | The backup CronJob has not succeeded in 26 hours | critical | A backup that silently stops is worse than no backup |
| `CertificateExpiringSoon` | Fewer than 14 days remaining on the served certificate | warning | The last line of defence before a browser warning |
| `CertificateRenewalFailed` | A cert-manager `Certificate` has had `Ready=False` for an hour | critical | Catches a stuck renewal about 30 days before anyone would see it in a browser. With a 90-day Let's Encrypt certificate this is the alert that matters, not the expiry one. |
| `GatewayNotProgrammed` | The platform `Gateway` reports `Programmed=False` for 5 minutes | critical | Every public endpoint is down, including Grafana, while the pods look healthy |
| `TraefikDown` | Fewer than 1 Traefik replica ready for 2 minutes | critical | The same, from the other direction |
| `NodeNotReady` | A node is not ready for 5 minutes | warning | Spot reclamation is expected, a stuck node is not |
| `PodCrashLooping` | More than 3 restarts in 15 minutes | warning | A bad release |

Every alert carries a `runbook_url` annotation pointing at the matching section of `docs/ops/runbooks.md`. An alert without a documented first step is noise.

### RED

| Test | Asserts |
|---|---|
| `tests/unit/test_prometheus_rules.py::test_rules_are_valid` | `promtool check rules` passes |
| `::test_every_alert_has_a_runbook_url` | Every rule has the annotation, and the target section exists in the runbook file |
| `::test_every_alert_has_severity` | Severity is `warning` or `critical`, nothing else |
| `::test_dashboards_are_valid_json` | Every dashboard file parses and declares a `uid` |
| `tests/platform/test_observability.py::test_prometheus_is_healthy` | The Prometheus pods are ready and the configuration is loaded |
| `::test_all_application_targets_are_up` | Prometheus scrapes all three services successfully in both namespaces |
| `::test_application_metrics_are_present` | All six custom metrics from Block 02 return data |
| `::test_grafana_api_health` | `GET /api/health` returns 200 over HTTPS |
| `::test_grafana_token_can_query_prometheus` | The proxy query above returns a value with a read-only token |
| `::test_grafana_token_cannot_write` | The same token gets 403 when trying to create a dashboard. **A read-only token that can write is not read-only.** |
| `::test_dashboards_are_provisioned` | Both dashboards are present and every panel returns data rather than "No data" |
| `::test_worker_down_fires_an_alert` | Scale the worker to 0, push votes, and `WorkerNotProcessing` reaches the `firing` state within 7 minutes. **This is the test that proves the alerting path works, which is the only thing that matters about an alert.** |

### GREEN

Deploy the stack through Argo CD, write the rules and dashboards, create the service account token, and run the alert test for real. Restore the worker afterwards.

### Done When

- All tests pass.
- Both dashboards show live data for `vote-prod`.
- The `curl` commands above are in `docs/ops/observability.md` and have been run against the live system.
- Every alert is listed in the runbook with a first step.
- The read-only token is stored in Secrets Manager and the README explains how a reviewer can request it.

---

## Block 11 — Data Persistence and Recovery

**Branch:** `block/11-data`
**Depends on:** Block 08

### Goal

The data survives a pod restart, a node loss, and a mistaken deletion. The restore procedure is proven by running it, not by writing it.

### Deliverables

| File | Purpose |
|---|---|
| `infra/terraform/modules/platform/backup.tf` | S3 bucket with versioning, a 30-day lifecycle rule, encryption, public access blocked, plus the IRSA role for the backup job |
| `deploy/helm/wtt-vote/templates/backup-cronjob.yaml` | A nightly `pg_dump` to S3 |
| `deploy/helm/wtt-vote/templates/pvc-retain.yaml` | Storage class with `reclaimPolicy: Retain` for PostgreSQL |
| `scripts/restore-postgres.sh` | The restore script, taking a backup key as its only argument |
| `docs/ops/runbooks.md` | The data sections: backup verification, restore, volume expansion, recovery after node loss |

Backup design:

- `pg_dump -Fc` once per day at 02:00 UTC, written to `s3://wtt-demo-backups/postgres/<date>.dump`.
- The job writes a Prometheus metric through a push gateway, or more simply updates a ConfigMap with the timestamp of the last success, which the `BackupJobFailed` alert reads. Pick one and write down why.
- 30-day retention through a lifecycle rule. Longer is pointless for a demonstration, and saying so is better than a silent default.
- The PostgreSQL volume uses `reclaimPolicy: Retain`, so deleting the StatefulSet does not delete the data.

### RED

| Test | Asserts |
|---|---|
| `tests/unit/test_backup_manifests.py::test_cronjob_schedule_is_daily` | The schedule is `0 2 * * *` |
| `::test_cronjob_uses_irsa` | The service account has the role annotation and no static credential |
| `::test_bucket_blocks_public_access` | The Terraform resource sets all four public access block settings |
| `::test_bucket_has_versioning_and_encryption` | Both are enabled |
| `::test_postgres_storage_class_retains` | `reclaimPolicy: Retain` |
| `tests/platform/test_data_durability.py::test_data_survives_pod_delete` | Submit 3 votes, delete the PostgreSQL pod, and after it restarts all 3 votes are still counted |
| `::test_data_survives_node_drain` | Drain the node hosting PostgreSQL. The pod reschedules, the volume reattaches, and the data is intact. |
| `::test_backup_job_produces_an_object` | Trigger the CronJob by hand and confirm a new object appears in S3 with a non-zero size |
| `::test_backup_is_restorable` | Download the dump, restore it into a throwaway PostgreSQL pod, and confirm the row count matches. **A backup that has never been restored is not a backup.** |
| `::test_full_restore_procedure` | Record the vote count, delete the whole `votes` table, run `scripts/restore-postgres.sh` exactly as written in the runbook, and confirm the count is back. Time the procedure and record the number. |
| `::test_redis_queue_survives_restart` | Push votes with the worker stopped, restart Redis, and the votes are still processed once the worker returns |

`test_full_restore_procedure` must run the documented script with no extra steps. If an undocumented step is needed, the documentation is wrong, and the documentation is the deliverable.

### GREEN

Write the Terraform, the CronJob, and the restore script, then run the two restore tests for real.

### Done When

- All tests pass.
- The runbook records the measured recovery time objective, from the real run.
- One backup object exists in S3 and has been restored successfully at least once.
- The `BackupJobFailed` alert fires when the CronJob is deliberately broken, and recovers when it is fixed. Test this once.

---

## Block 12 — Security Hardening

**Branch:** `block/12-hardening`
**Depends on:** Blocks 09, 10, 11

### Goal

Close the gap between "it works" and "it is safe to leave running on the public internet". Every control is verified by a test that tries to break it.

### Deliverables

| Area | Control |
|---|---|
| Network | Default-deny `NetworkPolicy` in both namespaces, then explicit allows: `vote` to `redis`, `worker` to `redis` and `postgres`, `result` to `postgres`, the `traefik` namespace to `vote` and `result`, Prometheus to all metrics ports, everything to CoreDNS. Nothing else. |
| Pod Security | `restricted` enforced on all four namespaces, which Block 07 already set up and this block verifies |
| Containers | `readOnlyRootFilesystem: true` with explicit `emptyDir` mounts where a service needs to write, `allowPrivilegeEscalation: false`, all capabilities dropped, `seccompProfile: RuntimeDefault` |
| RBAC | One service account per workload, no `default` service account in use, `automountServiceAccountToken: false` where the pod does not call the API |
| Quotas | `ResourceQuota` and `LimitRange` in both namespaces, so `vote-dev` cannot starve `vote-prod` |
| Edge | HTTP redirected to HTTPS by the route filter, TLS 1.2 as the minimum in the Traefik TLS options, a modern cipher list, and the three security response headers set by a `ResponseHeaderModifier` filter on each route |
| Images | Trivy findings from Block 03 reviewed, every HIGH or CRITICAL either fixed by a base image update or recorded in `.trivyignore` with a reason and an expiry date |
| Supply chain | `cosign verify` as a documented step before a promotion |

### RED

| Test | Asserts |
|---|---|
| `tests/unit/test_security_manifests.py::test_default_deny_exists` | Both namespaces have a policy selecting all pods with no ingress or egress rule |
| `::test_no_default_service_account_in_use` | No workload uses `default` |
| `::test_all_containers_read_only_root` | True for every container |
| `::test_seccomp_profile_set` | `RuntimeDefault` everywhere |
| `::test_quotas_defined_for_both_namespaces` | Both exist and the dev quota is smaller |
| `::test_trivyignore_entries_have_reason_and_expiry` | Every line has both, and no entry is past its expiry date. **Without this, `.trivyignore` becomes a place where problems go to be forgotten.** |
| `::test_tls_options_set_minimum_version` | The Traefik `TLSOption` object sets `minVersion: VersionTLS12` and an explicit cipher list |
| `tests/platform/test_security_controls.py::test_vote_cannot_reach_postgres` | From the `vote` pod, a TCP connection to `postgres:5432` times out. `vote` has no reason to reach the database. |
| `::test_prod_cannot_reach_dev` | From a `vote-prod` pod, a connection to a `vote-dev` service fails |
| `::test_prod_route_cannot_attach_to_dev_listener` | An `HTTPRoute` in `vote-dev` that names the production hostname is rejected by the `Gateway`, not silently served. The Gateway API boundary has to hold in the cluster, not only in the manifest. |
| `::test_pods_cannot_reach_the_instance_metadata_service` | `169.254.169.254` is unreachable from an application pod, so a compromised pod cannot borrow the node's IAM role |
| `::test_privileged_pod_is_rejected` | Applying a pod with `privileged: true` into `vote-prod` is refused by the admission controller |
| `::test_root_pod_is_rejected` | The same for `runAsUser: 0` |
| `::test_http_redirects_to_https` | `http://wtt-demo.syachin.de` returns a 301 to `https://` |
| `::test_tls_version_floor` | A TLS 1.0 and a TLS 1.1 handshake are both refused |
| `::test_security_headers_present` | `Strict-Transport-Security`, `X-Content-Type-Options`, and `X-Frame-Options` are all set, by the route filter from Block 05 |
| `::test_cosign_verify_passes_for_running_image` | The image running in `vote-prod` has a valid signature |

### GREEN

Add the controls one at a time and run the tests after each. Network policies are the most likely to break the application; add the default-deny policy first, watch what breaks, and add allows based on the actual failures rather than on a guess.

Two failures are predictable here. A default-deny policy with no rule for the `traefik` namespace takes the whole site offline while leaving every pod healthy, which looks like a gateway problem and is not. A default-deny policy with no egress rule for CoreDNS breaks name resolution everywhere, including cert-manager's DNS-01 solver, so a certificate renewal starts failing silently weeks before the certificate expires.

### Done When

- All tests pass.
- The application still works end to end after every control is in place. Run the Block 02 integration tests against `vote-prod`.
- `docs/ops/runbooks.md` has a section on diagnosing a network policy problem, written from the experience of breaking the application in this block.
- Every Trivy finding is either fixed or recorded with a reason and an expiry date.

---

## Block 13 — Final Documentation and Demo Readiness

**Branch:** `block/13-release`
**Depends on:** Block 12

### Goal

A reviewer who has never seen the project can understand it, verify it, and operate it. An engineer who takes it over can keep it running. This block produces no new infrastructure.

### Deliverables

| File | Content |
|---|---|
| `docs/ops/runbooks.md` | Complete. Every alert from Block 10 has a procedure, plus day-to-day operations |
| `docs/ops/disaster-recovery.md` | The full rebuild procedure and the result of the real drill |
| `docs/arch/overview.md` | Updated to match what was actually built, including every deviation from the original design and why |
| `docs/adr/*` | Every ADR reviewed. Any decision that changed during the work gets a superseding ADR, not an edit. |
| `docs/dev/demo-script.md` | A 10-minute walkthrough for the interview |
| `README.md` | Final: working links, a real architecture diagram, and the verification commands |
| `CHANGELOG.md` | One entry per block |
| `VERSION` | Set to `1.0.0` |

Required runbook sections, at a minimum:

```
Standard environment
Where to look first
Daily checks
Deploy a new version
Roll back a release
One section per alert defined in Block 10, matching the alert name
Restore the database
Rotate a secret
Scale the application
Expand a volume
Replace a failed node
Diagnose a routing or network policy problem
Recover Argo CD
Rebuild the platform from nothing
Tear everything down and confirm zero cost
```

The alert sections are not a fixed list. `test_every_alert_has_a_runbook_section` reads the alert names out of the `PrometheusRule` files and requires a matching heading for each, so adding an alert in a later block automatically requires a procedure for it. That is the point: an alert with no documented first step is noise.

### RED

| Test | Asserts |
|---|---|
| `tests/unit/test_documentation.py::test_no_broken_internal_links` | Every relative Markdown link resolves to a file that exists |
| `::test_every_alert_has_a_runbook_section` | Every alert name from the `PrometheusRule` files appears as a heading in the runbook |
| `::test_all_required_runbook_sections_exist` | Every section in the list above is present |
| `::test_no_unfinished_work_markers` | No unfinished-work marker remains in any file under `docs/`. The marker list lives in the test itself, so that naming the markers in a document does not trip the check. |
| `::test_roadmap_blocks_all_done` | Every block in the roadmap has status `done` |
| `::test_every_adr_has_a_status` | Every ADR declares `Accepted`, `Superseded`, or `Rejected`, and nothing is still `Proposed` |
| `::test_documentation_is_english_only` | No Cyrillic or German character outside a quoted proper noun. **This enforces the language rule mechanically instead of by memory.** |
| `::test_readme_links_are_reachable` | Every `https://` link in the README returns a successful status |
| `tests/e2e/test_public_service.py::test_voting_page_loads` | `https://wtt-demo.syachin.de/` returns 200 with valid TLS |
| `::test_vote_is_recorded_and_displayed` | Submit a vote over HTTPS and see the count change on the result page |
| `::test_no_mixed_content` | No resource on the page is loaded over plain `http://`. The final proof that D5 is fixed. |
| `::test_grafana_health_is_public` | `GET /api/health` returns 200 |
| `::test_metrics_api_answers_with_token` | The proxy query returns live data |
| `::test_response_time_budget` | The 95th percentile of 50 requests to `/` is under 800 ms |
| `tests/platform/test_disaster_recovery.py::test_rebuild_from_nothing` | Destroy the `vote-prod` namespace entirely. Argo CD recreates it, the database is restored from the latest backup, and the service answers correctly. Record the measured time. |

### GREEN

Write the documentation, run the drill, and record the real numbers.

### Done When

- All tests pass.
- The end-to-end suite runs on a schedule, every 6 hours, against the live service, so a silent failure is noticed before the interview rather than during it.
- The disaster recovery drill has been performed and the measured recovery time is in the document.
- The demo script has been rehearsed once against the live system.
- `git log --oneline` reads as a clear story, one merge per block.

---

## Verification Summary

| Block | Blocking tests | Needs AWS | Runs in CI |
|---|---|---|---|
| 00 | 7 | no | yes |
| 01 | 11 | no | yes |
| 02 | 12 | no | yes |
| 03 | 7 | no | yes |
| 04 | 10 | no, except the registry test | yes |
| 05 | 22 | no, uses `kind` | yes |
| 06 | 17 | yes | static only |
| 07 | 22 | yes | static only |
| 08 | 13 | yes | unit only |
| 09 | 9 | yes | unit only |
| 10 | 12 | yes | unit only |
| 11 | 11 | yes | unit only |
| 12 | 18 | yes | unit only |
| 13 | 15 | yes | end-to-end on a schedule |
| **Total** | **186** | | |

The routing decision in [ADR 0015](../adr/0015-traefik-gateway-api.md) moved seven tests into Block 05, where they run in `kind` on every push. Before that decision the whole routing layer was first exercised by hand on live AWS in Block 07.

Tests that need AWS are run by hand and the command plus its output go into the pull request. Tests that do not need AWS run on every push. The split is deliberate: a robot with the right to change infrastructure is a larger risk than the convenience is worth for a project of this size.

## The Six Tests That Matter Most

If time runs short, these are the ones to keep. Each one proves that a claim in the README is true.

| Test | Claim it proves |
|---|---|
| `test_revote_replaces_and_does_not_duplicate` | The application is correct, not just running |
| `test_self_heal_reverts_a_manual_change` | GitOps is real, not decoration |
| `test_full_restore_procedure` | The backup works and the runbook is accurate |
| `test_worker_down_fires_an_alert` | The alerting path works end to end |
| `test_pods_cannot_reach_the_instance_metadata_service` | The security boundary holds |
| `test_allowed_routes_restricts_namespaces` | The Gateway API role boundary is enforced by the API server, not by convention |
| `test_rebuild_from_nothing` | The platform is reproducible |
