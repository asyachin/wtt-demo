# 0012 — One Python Test Harness, and Trivy Does Not Block

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The project has to verify things in six different shapes: Python code, Node.js code, C# code, Helm templates, Terraform configuration, and live AWS and Kubernetes state. The author's language is Python and the preferred way of working is test-first. [ADR 0002](0002-keep-polyglot-application.md) keeps the application in three languages, so test-first in Python is not available for two of the three services.

There is also a question about the container vulnerability scanner. The requirement is explicitly for a non-strict Trivy check, and that needs a reason rather than just an implementation.

## Options Considered

### Harness

| Option | Advantage | Disadvantage |
|---|---|---|
| One Python and pytest harness for every layer, testing other languages from the outside | One command, one report, one set of fixtures, one skill. Behaviour is tested rather than implementation. | A failure in `result` or `worker` points at an endpoint rather than a line of code |
| A native framework per language, plus a separate end-to-end suite | Precise unit coverage in every service | Four frameworks, four report formats, four places to look. Most of the coverage would be written in languages the author does not work in. |
| Shell scripts with `curl` and `grep` | No dependency | No fixtures, no teardown, no useful failure message, and it rots within weeks |

### Container scanning

| Option | Advantage | Disadvantage |
|---|---|---|
| Report, do not block | Delivery never stops for a finding with no available fix. Findings are visible and triaged as real work. | A finding can be ignored indefinitely unless something forces the triage |
| Block on HIGH and CRITICAL | Strongest signal | A base image can gain a critical finding overnight with no fixed version. All delivery stops for something nobody can act on, and somebody adds a bypass that then stays forever. |
| Do not scan | No noise | No idea what is being shipped |

## Decision

Python with pytest is the single harness for all four test layers. Node.js, .NET, Helm, Terraform, AWS, and Kubernetes are all tested from the outside: through HTTP endpoints, through rendered manifests, through the cloud API, and through their effects on PostgreSQL and Redis. Native linters and formatters still run per language in the `lint` job.

Four layers, each with one marker, enforced by `--strict-markers`:

| Layer | Marker | Needs | Budget |
|---|---|---|---|
| Unit | `unit` | nothing | 30 seconds |
| Integration | `integration` | Docker Compose | 4 minutes |
| Platform | `platform` | a Kubernetes cluster | 10 minutes |
| End to end | `e2e` | the deployed public service | 2 minutes |

Trivy runs with `--exit-code 0` and never fails a build. It uploads SARIF to the GitHub security tab and writes a job summary on every run. Findings are triaged as real work in Block 12, where each one is either fixed by a base image update or recorded in `.trivyignore` with a written reason and an expiry date.

One check is strict in the opposite direction: a vulnerability in the project's own dependencies, found by `pip-audit` or `npm audit --omit=dev`, does fail the build.

## Reasoning

### One harness

One place to look, one command to run, one report to read. For a project maintained by one person, that is worth more than precise unit coverage in a language that person does not write.

Testing from the outside also tests the right thing. `test_revote_replaces_and_does_not_duplicate` is a Python test that proves a .NET upsert and a PostgreSQL primary key work together. A C# unit test with a mocked database would assert that the code calls `ON CONFLICT`; the Python test asserts that the row count is correct, which is the actual requirement. The defect it catches, D1, would have survived a mocked unit test.

The same applies to `test_vote_survives_database_restart`, which proves D2 is fixed by restarting a container, and `test_no_password_in_any_log`, which proves D3 is fixed by reading the logs. None of those three has a natural home in a C# unit test.

The cost is accepted and stated: a failure in `result` or `worker` points at an endpoint or a row count rather than a line number, so debugging starts with `docker compose logs`. For twelve known defects in software that is otherwise unchanged, that is an acceptable trade.

The layer rules in `docs/dev/testing-strategy.md` are what keeps this from degenerating. An `e2e` test that needs `kubectl` is a `platform` test in the wrong directory, and without a stated rule that distinction erodes until no layer means anything.

### Trivy does not block

A blocking scanner on a base image is a pipeline that can stop for a reason nobody in the project can act on. A critical finding appears in a `python:3.11-slim` layer, no fixed version exists yet, and all delivery halts. The predictable response is a bypass flag, and the bypass outlives the finding by years. A gate that gets bypassed is worse than no gate, because it is also dishonest.

So the scan reports, and Block 12 turns the report into work. The guard against indefinite drift is the ignore file discipline: `test_trivyignore_entries_have_reason_and_expiry` fails if an entry lacks either, or if an entry is past its expiry date. That makes `.trivyignore` a list of decisions with dates rather than a place where problems go to be forgotten.

The strict line is drawn where the project has authority. A vulnerable version of Flask or Express is the project's own choice, it can always be changed, so `pip-audit` and `npm audit` block the build. A vulnerable `libsystemd` in a Debian base layer is not the project's choice, so it is reported and triaged. The distinction is between findings the project can act on and findings it cannot.

## Consequences

### Positive

- One command, `make ci`, runs everything, locally and in CI, in the same order.
- Behaviour is tested rather than implementation, which is what the twelve defects need.
- Test-first works for the whole project, including the parts written in other languages.
- Delivery never halts for an unfixable base image finding.
- Vulnerabilities the project controls are hard blockers.
- The ignore file cannot silently accumulate.

### Negative

- Unit coverage is only meaningful for `vote`. The coverage gate of 70 percent applies to `app/vote` alone, and `result` and `worker` are covered only at the integration level, which is slower and less precise.
- A `result` or `worker` failure gives an endpoint, not a line number.
- Integration tests need Docker, so they are slower and can be flaky under load. The `eventually` fixture with explicit deadlines replaces every `sleep`, which helps but does not eliminate it.
- A non-blocking scanner depends on Block 12 actually happening. If the project stopped at Block 11, the findings would never be triaged.
- Platform tests are run by hand, not in CI, so there is no automatic protection against an infrastructure regression. This follows from not giving a CI robot the right to apply infrastructure, and the command plus its output go into the pull request instead.

### Neutral

- 166 tests across 14 blocks. Roughly 12 per block, which is a reasonable amount to write in one sitting.
- `helm unittest` is used only for template logic that `helm template` plus Python cannot reach, so it stays a small exception rather than a second harness.

## Verification

- `tests/unit/test_ci_contract.py` asserts that the pipeline has every required job, that `scan` passes `--exit-code 0`, and that the gate job depends on every blocking job.
- `test_trivyignore_entries_have_reason_and_expiry` in Block 12.
- `--strict-markers` in `pyproject.toml` fails collection for any test without exactly one marker.
- A deliberately broken test is confirmed to produce a red pipeline once, by hand, in Block 03. An untested gate is not a gate.

## Revisit When

A second engineer joins who works in Node.js or C#, which makes native unit tests worth their cost. Or a base image finding turns out to be exploitable in this deployment, which justifies blocking on that specific finding rather than on the whole class.
