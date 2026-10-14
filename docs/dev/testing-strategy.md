# Testing Strategy

## Principle

A test exists to prove one claim. If a claim in the README or in an ADR cannot be checked by a test, either the claim is removed or a test is written. Documentation that nothing verifies becomes wrong without anybody noticing.

This project uses a test-first cycle. The tests for a block are written and pushed in a failing state before the implementation exists. See [git-workflow.md](git-workflow.md).

## One Harness, Four Layers

Python with pytest is the harness for every layer, including the layers that test Node.js, .NET, Helm, Terraform, and AWS. Those components are tested from the outside, through their HTTP endpoints, their rendered manifests, or the cloud API. Native unit tests stay in their own toolchain and are run by the `lint` and `unit` jobs.

The reason for one harness is simple: one place to look, one command to run, one set of fixtures, one report. The reasoning is in [ADR 0012](../adr/0012-testing-strategy.md).

| Layer | Marker | Needs | Runs | Budget |
|---|---|---|---|---|
| Unit | `unit` | nothing. No network, no containers, no cloud. | Every push | under 30 seconds |
| Integration | `integration` | Docker and the local Compose stack | Every push | under 4 minutes |
| Platform | `platform` | A Kubernetes cluster. `kind` in CI for the chart and the whole routing layer, the real EKS cluster for the rest. | `kind` tests on every push, EKS tests by hand | under 10 minutes |
| End to end | `e2e` | The deployed public service | On a schedule every 6 hours, and after every promotion | under 2 minutes |

A test must declare exactly one marker. A test with no marker fails the collection step, which is enforced by `--strict-markers` in `pyproject.toml`.

## What Each Layer Is Allowed to Assume

This is the part that keeps a suite from rotting.

| Layer | May assume | May not |
|---|---|---|
| `unit` | The source files are on disk. The application module can be imported. | Any network call, any container, any cloud credential, any clock dependency |
| `integration` | The Compose stack is up and healthy, and the credentials come from the `dev` environment. | Anything about AWS, Kubernetes, or the public hostname |
| `platform` | A kubeconfig points at a cluster, and the application is installed in a known namespace. | A specific pod name, a specific node, or a specific IP address |
| `e2e` | `https://wtt-demo.syachin.de` is reachable from the internet. | Any access to the cluster, any credential beyond the read-only Grafana token |

An `e2e` test that needs `kubectl` is a `platform` test that has been put in the wrong directory.

## Layout

```
tests/
├── conftest.py              Shared fixtures, marker registration, the --base-url option
├── requirements.txt         Pinned test dependencies
├── unit/
│   ├── test_repository_hygiene.py
│   ├── test_dockerfiles.py
│   ├── test_vote_app.py
│   ├── test_ci_contract.py
│   ├── test_image_tag.py
│   ├── test_publish_workflow.py
│   ├── test_helm_chart.py
│   ├── test_argocd_manifests.py
│   ├── test_no_secrets_in_repo.py
│   ├── test_prometheus_rules.py
│   ├── test_backup_manifests.py
│   ├── test_security_manifests.py
│   └── test_documentation.py
├── integration/
│   ├── test_image_properties.py
│   ├── test_vote_flow.py
│   └── test_published_images.py
├── platform/
│   ├── test_terraform_static.py
│   ├── test_chart_on_kind.py
│   ├── test_eks_cluster.py
│   ├── test_platform_addons.py
│   ├── test_argocd.py
│   ├── test_secrets_delivery.py
│   ├── test_observability.py
│   ├── test_data_durability.py
│   ├── test_security_controls.py
│   └── test_disaster_recovery.py
└── e2e/
    └── test_public_service.py
```

One file per block, named after what it proves. A file that grows past about 300 lines is split by subject, not by size.

## Tools

| Purpose | Tool | Why this one |
|---|---|---|
| Test runner | `pytest` | Markers, fixtures, and parametrisation without extra machinery |
| HTTP | `requests` | Enough for every case here |
| PostgreSQL | `psycopg[binary]` | Direct row checks in integration tests |
| Redis | `redis` | Queue depth checks |
| Kubernetes | `kubernetes` | Reads the API instead of parsing `kubectl` output |
| AWS | `boto3` | Same reason |
| Retrying | `tenacity` | A distributed system needs a deadline, not a `sleep` |
| Python lint and format | `ruff` | One tool instead of four |
| Python dependency audit | `pip-audit` | Fails the build. These are the application's own dependencies. |
| Node lint | `eslint` | Standard |
| Node dependency audit | `npm audit --omit=dev` | Fails the build |
| .NET format | `dotnet format` | Standard |
| Dockerfile lint | `hadolint` | Catches the common mistakes |
| YAML lint | `yamllint` | Catches indentation errors before Kubernetes does |
| Manifest schema | `kubeconform`, with the Gateway API CRD schemas added | Validates rendered manifests against the real API schema. The Gateway API schemas must be loaded explicitly or every `HTTPRoute` passes without being checked. |
| Helm unit tests | `helm unittest` | For template logic that is hard to reach through `helm template` |
| Prometheus rules | `promtool` | The only correct validator for a rule file |
| Terraform lint | `tflint` | Provider-aware checks |
| Terraform security | `checkov` | Finds the misconfiguration before AWS does |
| Secret scanning | `gitleaks` | Full history, on every push |
| Image scanning | `trivy` | Reports, does not block. See below. |
| Image signing | `cosign` | Keyless, using the GitHub Actions identity |

## Blocking and Non-Blocking Checks

| Check | Blocks a merge | Reason |
|---|---|---|
| `ruff`, `eslint`, `dotnet format`, `hadolint`, `yamllint` | yes | Cheap, deterministic, no false positives worth arguing about |
| `pytest -m unit` | yes | The contract of the code |
| Coverage of `app/vote` below 70 percent | yes | Only the Python service has a meaningful coverage target. The other two are covered through integration tests. |
| `pytest -m integration` | yes | The contract between the services |
| `pip-audit`, `npm audit --omit=dev` | yes | The project's own dependencies are the project's responsibility |
| `gitleaks` | yes | A leaked secret cannot be undone |
| `kubeconform`, `helm lint`, `promtool`, `terraform validate` | yes | A broken manifest breaks a deployment |
| `checkov` above medium severity | yes, unless listed with a reason | Infrastructure mistakes are expensive |
| `trivy image` | **no** | See below |
| `pytest -m platform` | not a merge gate | Needs a real cluster, run by hand with the output in the pull request |
| `pytest -m e2e` | not a merge gate | Runs after deployment, on a schedule |

### Why Trivy Does Not Block

A base image can gain a critical finding overnight, with no fixed version available. A pipeline that blocks on that stops all delivery for a reason nobody can act on, and the predictable result is that someone adds a bypass and the bypass stays forever.

So the scan runs with `--exit-code 0`, uploads SARIF to the GitHub security tab, and writes a summary table on every run. The findings are then handled as real work in Block 12: fixed by a base image update, or recorded in `.trivyignore` with a written reason and an expiry date. A unit test checks that every ignore entry has both and that none is past its expiry, so the ignore file cannot quietly become a landfill.

The strict line is drawn in a different place: a vulnerability in the application's own dependencies, found by `pip-audit` or `npm audit`, does fail the build. That is a finding the project can always act on.

## Fixtures

The important ones, defined in `tests/conftest.py`.

| Fixture | Scope | Provides |
|---|---|---|
| `repo_root` | session | The repository root, found from `git rev-parse` |
| `compose_stack` | session | A healthy Compose stack, torn down afterwards. Used by every `integration` test. |
| `pg` | function | A PostgreSQL connection, with the `votes` table truncated before the test |
| `rds_queue` | function | A Redis client, with the `votes` list cleared before the test |
| `vote_url`, `result_url` | session | Base URLs, taken from `--base-url` or from the Compose port mapping |
| `k8s` | session | A Kubernetes API client from the current kubeconfig |
| `namespace` | session | The namespace under test, from `--namespace`, default `vote-dev` |
| `helm_render` | session | Renders the chart with a given value file and returns parsed manifests |
| `aws` | session | A `boto3` session for the configured region |
| `eventually` | function | A helper that retries an assertion until a deadline. Replaces every `time.sleep`. |

## Rules for Writing Tests

- One claim per test. The test name is a sentence about the claim.
- No `time.sleep`. Use `eventually` with an explicit deadline, and let the failure message name what never became true.
- No test depends on another test, and no test depends on the order of execution.
- Every test cleans up what it creates, in a fixture teardown, so that a failing test does not leave the environment dirty.
- A test that is flaky is either fixed or deleted in the same day. A suite that is sometimes red teaches everyone to ignore red.
- A test never asserts on a log line unless the log line is the thing being tested, as in `test_no_password_in_any_log`.
- No `platform` test ever runs against `vote-prod` except the read-only ones. The destructive drills use a throwaway namespace or `vote-dev`, with one exception: the disaster recovery drill in Block 13, which deliberately destroys `vote-prod` and is run once, by hand, with the result recorded.

## Running Tests

```
make lint               # every linter and formatter check
make test-unit          # pytest -m unit
make test-integration   # brings the Compose stack up, runs pytest -m integration, tears it down
make test-chart         # helm lint, kubeconform, and the kind tests
make scan               # trivy on all three images, plus trivy config
make ci                 # everything that CI runs, in the same order

# Platform tests, against a real cluster
pytest -m platform --namespace vote-dev

# End to end, against the public service
pytest -m e2e --base-url https://wtt-demo.syachin.de
```

`make ci` must produce the same result on a laptop as in GitHub Actions. If the two differ, the pipeline is wrong, not the laptop.

## Coverage of the Plan

| Claim the project makes | Test that proves it | Block |
|---|---|---|
| The images are small and do not run as root | `test_image_size_budget`, `test_image_runs_as_non_root` | 01 |
| Vote counting is correct | `test_revote_replaces_and_does_not_duplicate` | 02 |
| A dependency outage does not restart the pod | `test_healthz_returns_200_without_redis` | 02 |
| Secrets never appear in logs | `test_no_password_in_any_log`, `test_password_not_in_pod_logs` | 02, 09 |
| Development and production differ only where intended | `test_dev_and_prod_differ_only_in_allowed_keys` | 05 |
| Routing, including the websocket and the redirect, is correct | `test_routing_matches_paths`, `test_websocket_upgrade_succeeds` | 05 |
| The Gateway API role boundary is enforced by the cluster | `test_allowed_routes_restricts_namespaces` | 05 |
| The edge path works: DNS, TLS, load balancer, pod | `test_sample_route_answers_over_https`, `test_served_certificate_is_trusted` | 07 |
| The cluster state comes from Git | `test_self_heal_reverts_a_manual_change` | 08 |
| A rollback needs no manual cluster access | `test_rollback_by_revert` | 08 |
| Secret rotation works as documented | `test_rotation_propagates` | 09 |
| The read-only token is really read-only | `test_grafana_token_cannot_write` | 10 |
| Alerts reach a firing state | `test_worker_down_fires_an_alert` | 10 |
| The backup can be restored | `test_backup_is_restorable`, `test_full_restore_procedure` | 11 |
| A compromised pod cannot borrow the node role | `test_pods_cannot_reach_the_instance_metadata_service` | 12 |
| The platform is reproducible | `test_rebuild_from_nothing` | 13 |
| The documentation is accurate | `test_no_broken_internal_links`, `test_every_alert_has_a_runbook_section` | 13 |
