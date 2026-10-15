# Block 00 — Repository Foundation

| Field | Value |
|---|---|
| Status | `CLOSED` |
| Branch | `block/00-bootstrap`, merged as `4667c11` |
| Depends on | — |
| Next | Block 01 |
| Report type | **Retrospective reconstruction**, written 15 October 2026 from the original plan and the commit history |

This report was written after the work, during the Phase 3 documentation reconciliation. It describes what the commits show. It does not present a detailed execution plan that was never written down at the time.

## Goal

Turn an imported directory into a repository with a clean history, remove the previous project's configuration, and make it impossible to commit a secret or build output by accident.

## Observed implementation

From the three commits on `block/00-bootstrap`:

| Commit | Subject | What it did |
|---|---|---|
| `cecfd3c` | `test: establish failing repository hygiene checks (RED)` | Added `tests/unit/test_repository_hygiene.py` in a failing state, plus `tests/conftest.py`, `tests/requirements.txt` and `pyproject.toml` |
| `0566c94` | `fix: secure local stack and restore application startup (GREEN)` | Made the tests pass: ignore rules, removal of the stale `.env` symlink and committed build output, corrected `app/.env.template`, repaired `docker-compose.yml` |
| `2d1049f` | `chore: add local PostgreSQL password rotation utility` | Added `scripts/pass.py` and `scripts/pg_pass_rotation.py` |

The red-then-green sequence is visible in the history, which is the evidence that the tests were written first and were capable of failing.

Delivered:

- `.gitignore`, `.dockerignore`, `app/.dockerignore` and one `.dockerignore` per service. The three service files are allow-lists — `*` first, then the files the image needs — so that nothing unexpected can enter a build context.
- `.editorconfig`, `.gitattributes`, `pyproject.toml` with ruff and pytest configuration.
- `app/.env.template` with keys and no values.
- `app/docker-compose.yml` for the local stack, using PostgreSQL 17 and Redis 7.4.
- 12 unit tests in one file.

Removed: the `app/.env` symlink into a previous project's secret directory, the committed `app/worker/obj/` build output containing another developer's absolute paths, `app/docker-compose.deploy.yml` with plaintext credentials and `NODE_TLS_REJECT_UNAUTHORIZED=0`, and the `ns.tmp` scratch file holding a copy of a Route 53 record set.

## Acceptance criteria and evidence

Reconstructed from the tests that exist and pass.

| # | Criterion | Verification | Result |
|---|---|---|---|
| 1 | No `app/.env` symlink | `test_no_env_symlink` | Pass |
| 2 | Environment files ignored, template not | `test_gitignore_blocks_env_files` | Pass |
| 3 | Build output ignored and untracked | `test_gitignore_blocks_build_output`, `test_no_build_output_tracked` | Pass |
| 4 | No reference to the previous project remains | `test_no_previous_project_references` | Pass |
| 5 | `app/.env.template` parses as `KEY=VALUE` with no trailing comments | `test_env_template_is_parseable` | Pass |
| 6 | No credential value in the template | `test_env_template_has_no_credentials` | Pass |
| 7 | A `.dockerignore` exists for every build context, and the service files are allow-lists | `test_dockerignore_exists_per_build_context`, `test_service_dockerignores_are_allow_lists` | Pass |
| 8 | The legacy deployment compose file is gone | `test_legacy_deployment_compose_removed` | Pass |
| 9 | The database connection string is not logged | `test_database_connection_string_not_logged` | Pass |
| 10 | Infrastructure code is not accidentally ignored | `test_infrastructure_code_is_not_ignored` | **Defective — see below** |

Run the suite with:

```bash
python3 -m pytest tests/unit/test_repository_hygiene.py -v
```

## Deviations from plan

**One test does not test anything.** `test_infrastructure_code_is_not_ignored` asserts that `git check-ignore` returns 1 for four paths:

```
infra/terraform/env/platform/main.tf
infra/terraform/env/platform/terraform.tfvars
infra/terraform/env/platform/.terraform.lock.hcl
deploy/helm/wtt-vote/values-prod.yaml
```

None of these paths exists. The original plan expected a single Terraform root at `infra/terraform/env/platform/` and a Helm chart at `deploy/helm/wtt-vote/`; Block 01 used four separate roots instead, and no Helm chart was ever created. Because `git check-ignore` returns 1 for any path that is not ignored, whether or not it exists, the test passes vacuously.

The test was written in good faith against the layout the plan specified. It became meaningless when the layout changed, and nothing detected that. It is tracked as issue **T1** in [../application.md](../application.md#not-an-application-defect-tracked-here-for-completeness) and is repaired in [Block 04](04-demo-quality-gate.md).

**Scope was narrower than the original plan's Block 00.** The plan also called for a Gitleaks workflow, a pull request template and a `LICENSE` file. None was created. Secret scanning is part of Block 07, which owns CI.

## Risks and limitations after this block

- No automated secret scanning. Protection against committing a credential rests on the ignore rules and on review.
- No `LICENSE` file.
- The hygiene suite covers repository structure only. There is no test of application behaviour at this point.
- `.python-version` declares `3.15.0rc3` and ruff targets `py314`, while the `vote` image is built on `python:3.11-slim`. Inconsistent, and it weakens any claim of a reproducible toolchain.

## Definition of Done

- [x] Acceptance criteria verified by a passing test suite
- [x] No secret in the repository
- [x] Branch merged into `dev` as `4667c11`
- [x] Status `CLOSED`
- [x] Documentation updated — this report, written retrospectively in Phase 3
