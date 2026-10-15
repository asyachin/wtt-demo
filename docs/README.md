# Documentation index

Start with the [project README](../README.md) for a five-minute overview.

## What is true now

| Document | Answers |
|---|---|
| [architecture.md](architecture.md) | What is deployed, how traffic flows, how identity and TLS work, what it costs |
| [application.md](application.md) | The five workloads, their interfaces, and every known defect with its real status |

## Delivery

| Document | Answers |
|---|---|
| [roadmap.md](roadmap.md) | Block status, acceptance evidence, interview scope, deferred work |
| [blocks/](blocks/) | One report per block: goal, scope, criteria, evidence, deviations |
| [process.md](process.md) | Block lifecycle, Definition of Done, change control, documentation update procedure |

## Operations

| Document | Answers |
|---|---|
| [operations/reproduce.md](operations/reproduce.md) | How to rebuild this platform from an empty AWS account |
| [operations/verify.md](operations/verify.md) | How to check that each layer works |
| [operations/troubleshoot.md](operations/troubleshoot.md) | What to do when it does not |
| [operations/teardown.md](operations/teardown.md) | How to destroy it without leaving resources billing |

## History and decisions

| Document | Answers |
|---|---|
| [decisions/README.md](decisions/README.md) | Which decisions still apply, which were deferred, which were superseded |
| [decisions/initial/](decisions/initial/) | The original pre-implementation decision records, preserved unchanged |
| [reconciliation.md](reconciliation.md) | Where implementation diverged from the original plan, and why |
| [lessons.md](lessons.md) | Operational knowledge produced by the implementation |

## Reading the status language

Documents distinguish three things, deliberately and consistently:

- **Implemented and verified** — with the evidence and who observed it.
- **Implemented, verification outstanding** — built and deployed, not yet confirmed.
- **Not implemented** — planned, optional, or deferred, with the owning block.

No capability is described as working unless there is evidence. Where a check requires cluster or browser access that was unavailable at the time of writing, the document says so and names it as operator verification.
