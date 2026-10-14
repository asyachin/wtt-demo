# 0001 — Record Architecture Decisions

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-14 |
| Deciders | Alexander Syachin |
| Block | 00 |
| Supersedes | none |
| Superseded by | none |

## Context

This project is a demonstration of platform engineering practice, built to be reviewed by engineers. Almost every technical choice in it is a trade-off made under a cost or time constraint rather than an obviously correct answer.

A reviewer who sees only the result cannot tell the difference between a deliberate trade-off and an oversight. "PostgreSQL runs as a single pod" looks like carelessness unless the reasoning is written down, in which case it looks like judgement. The same is true for the reviewer that matters most in six months, which is the author.

## Options Considered

| Option | Advantage | Disadvantage |
|---|---|---|
| Architecture Decision Records in the repository | Versioned with the code, reviewed in the same pull request, no extra tool | Requires the discipline to write one at the time of the decision |
| A single long design document | One place to read | Becomes stale, and loses the reason a rejected option was rejected |
| No written decisions | No effort | Every trade-off looks like an accident |
| A wiki or an external document | Rich formatting | Separate from the code, diverges immediately, not reviewable in a pull request |

## Decision

Every significant decision is recorded as a numbered Markdown file in `docs/adr/`, following `template.md`. A record is written in the same pull request as the work it governs. A record is never edited once accepted; a changed decision gets a new record that supersedes the old one.

## Reasoning

The records live next to the code they describe, so they are reviewed by the same process and versioned by the same history. A `git log` on `docs/adr/` is a readable account of how the architecture came to be.

Immutability is the part that gives the practice its value. An edited record loses the information that something was once believed and then found to be wrong, and that information is often the most useful thing in the file.

The format is the common one, close to Michael Nygard's original, because an unfamiliar format costs a reader attention that should go to the content.

## Consequences

### Positive

- Every trade-off in the project can be read with its reasoning.
- A rejected option is recorded with its reason, so it is not reopened without new information.
- The records are a direct demonstration of the documentation skill the project is meant to show.

### Negative

- Writing a record takes 15 to 30 minutes, every time.
- A record written after the fact is a rationalisation rather than a decision, so the timing discipline matters and is easy to lose.
- Fourteen records written up front, before most of the implementation, carry the risk of being wrong. Each one that turns out wrong needs a superseding record rather than a quiet edit.

### Neutral

- A numbering scheme has to be maintained by hand.

## Verification

- `docs/adr/README.md` has a row for every file in `docs/adr/`.
- `test_every_adr_has_a_status` in Block 13 fails if any record is still `Proposed`.
- `test_no_broken_internal_links` fails if a record references a file that does not exist.

## Revisit When

Never. If the practice becomes a burden, the right response is fewer records with a higher bar, not no records.
