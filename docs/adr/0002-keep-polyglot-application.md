# 0002 — Keep the Application As It Is, in Three Languages

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

The workload is a fork of the Docker `example-voting-app`. It has three services in three languages: `vote` in Python with Flask, `result` in Node.js with Express and Socket.IO, and `worker` in C# on .NET 8. The data services are PostgreSQL and Redis.

The author's own language is Python, and the preferred way of working is test-first. That creates an obvious temptation to rewrite `result` and `worker` in Python, which would make one test framework cover everything.

The position being demonstrated is Platform and Systems Engineer. The deliverable is the platform: the infrastructure, the delivery pipeline, the observability, the security, and the documentation. The application is the thing being carried.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| Keep all three languages | No application work beyond defect fixes. The platform must handle three runtimes, which is the realistic case. | Three toolchains in CI. Test-first in Python is not possible for two of the three services. |
| Rewrite everything in Python | One toolchain, one test framework, full test-first coverage | Days spent writing application code that demonstrates the wrong skill. A rewrite introduces new defects in working software. |
| Rewrite only the worker | The worker is the smallest service and holds the trickiest defects | Still two runtimes, so the toolchain cost is paid anyway with half the benefit |

## Decision

The application keeps its three languages and its structure. The only changes are the twelve defect fixes and the health and metrics endpoints listed in `docs/arch/application.md`. No service is rewritten and no feature is added.

## Reasoning

A platform that handles exactly one runtime is not a platform, it is a deployment script. A polyglot workload forces the real work: three Dockerfiles with three different multi-stage patterns, three dependency audit tools, three ways to expose Prometheus metrics, three sets of base image vulnerabilities to triage. That is what the job involves.

The time saved by not rewriting goes into the parts that are being assessed. A rewrite would also mean replacing software that works with software that is new, and new software has new defects.

The cost is real: test-first in Python is not available for `result` and `worker`. That is handled rather than ignored. Python with pytest remains the single harness, and it tests those two services from the outside, through their HTTP endpoints and through their effects on PostgreSQL and Redis. Two of the three most valuable tests in the whole plan, `test_revote_replaces_and_does_not_duplicate` and `test_vote_survives_database_restart`, are Python tests that prove .NET behaviour. See [0012](0012-testing-strategy.md).

## Consequences

### Positive

- No time spent on application rewriting.
- The platform is forced to handle three runtimes, which makes the demonstration honest.
- The existing software keeps working, with twelve defects fixed on top.

### Negative

- CI needs Python, Node.js, and .NET toolchains, which makes the pipeline slower and larger.
- Unit test coverage is only meaningful for `vote`. The other two services are covered at the integration level, which is slower and less precise.
- A reviewer may read three languages as scope creep rather than as a deliberate constraint. The README and this record have to say otherwise.
- The AngularJS front end in `result` is long out of support. It is left alone because it works, is not internet-exposed to any input, and replacing it is application work.

### Neutral

- The .NET build stage is the largest single contributor to pipeline time.

## Verification

- `docs/arch/application.md` lists every defect and the block that fixes it.
- The twelve fixes are each proven by a named test in `docs/dev/deployment-plan.md`.
- `git diff` across Blocks 01 and 02 touches no file that adds a feature.

## Revisit When

A service needs a change large enough that rewriting it is cheaper than changing it. That is not true for any of the twelve defects.
