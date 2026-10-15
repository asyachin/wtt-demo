# Block NN — Title

| Field | Value |
|---|---|
| Status | `PLANNED` / `IN PROGRESS` / `BLOCKED` / `VERIFIED` / `CLOSED` |
| Branch | `block/NN-slug` |
| Depends on | Block NN |
| Next | Block NN |
| Report type | Written before implementation / Retrospective reconstruction |

## Goal

One paragraph. What becomes true when this block closes, and why that is worth doing.

## Scope

What this block delivers. One line per item, with an identifier if the block has several independent parts.

## Out of scope

What this block deliberately does not do, each with the block that owns it instead. This section prevents scope drift and stops a reviewer reading an omission as an oversight.

## Prerequisites

What must already exist or be verified before starting. Access, credentials, prior blocks.

## Planned work

Numbered steps in execution order, written before implementation begins.

For a retrospective report this section is titled **Observed implementation** instead, and describes what was done as evidenced by commits. It does not invent a plan that was never written.

## Acceptance criteria

Numbered, objective, independently checkable. No criterion may be satisfied by inspection alone: each needs a command, an observed output, or a named human observation with a date.

| # | Criterion | Verification | Expected |
|---|---|---|---|

## Evidence

Filled in as verification happens, never pre-filled. Commit hashes, commands with their real output, operator observations with dates and, for browser checks, the browser and version.

## Deviations from plan

Filled in at closure. Empty is a valid and good answer. Anything architectural is also added to [../reconciliation.md](../reconciliation.md).

## Risks and limitations

What is still not true after this block closes.

## Definition of Done

- [ ] Every acceptance criterion verified, with evidence recorded above
- [ ] Public demonstration still correct: [../operations/verify.md](../operations/verify.md) section 1 passes
- [ ] No secret, key or token added to the repository
- [ ] Documentation updated per [../process.md](../process.md#documentation-update-at-block-closure)
- [ ] Deviations recorded above, and in `reconciliation.md` if architectural
- [ ] Branch merged into `dev`
- [ ] Status set to `CLOSED` here and in [../roadmap.md](../roadmap.md)
