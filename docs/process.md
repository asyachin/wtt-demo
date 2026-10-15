# Delivery process

The process is deliberately small. Its purpose is that any claim in this repository can be traced to a commit and a verification, and that a deviation from plan is recorded rather than absorbed.

## Status vocabulary

| Status | Meaning |
|---|---|
| `PLANNED` | Acceptance criteria written and agreed. No work started. |
| `IN PROGRESS` | Branch exists, work underway. Some criteria may already be met. |
| `BLOCKED` | Cannot proceed. The blocker is named in the block report. |
| `VERIFIED` | Every acceptance criterion met and evidence recorded. Not yet merged. |
| `CLOSED` | Merged into `dev`, report complete, roadmap updated. |
| `OPTIONAL` | Valuable but not required for the current objective. No criteria agreed yet. |

A block moves to `CLOSED` only when its Definition of Done is fully satisfied. Partial completion stays `IN PROGRESS` with the outstanding items listed, which is why Block 04 is `IN PROGRESS` despite part of its scope being deployed.

## Block lifecycle

```
1. Write the block report from docs/blocks/template.md.
   Goal, scope, exclusions, prerequisites, planned work, acceptance criteria.
   Acceptance criteria are agreed BEFORE implementation starts.

2. Create branch block/NN-slug from dev.

3. Implement. Where a test-first cycle applies, push the failing state first,
   so that the test is shown to be capable of failing.

4. Verify each acceptance criterion. Record the command and its real output
   in the report's Evidence section. Nothing is pre-filled.

5. Record deviations. Empty is a valid and good answer.

6. Update documentation per the procedure below, in the same branch.

7. Confirm the Definition of Done, merge into dev, set status CLOSED.
```

Branches are kept after merge as implementation evidence. `dev` is the integration branch. `main` currently lags and is updated by a reviewed merge, not automatically.

## Definition of Done

Every block carries this checklist. A block that cannot tick every box is not done.

- [ ] Every acceptance criterion verified, with the command and its output recorded
- [ ] Public demonstration still correct: [operations/verify.md](operations/verify.md) section 1 passes
- [ ] No secret, key or token added to the repository
- [ ] Documentation updated per the procedure below
- [ ] Deviations recorded in the block report, and in [reconciliation.md](reconciliation.md) if architectural
- [ ] Branch merged into `dev`
- [ ] Status set to `CLOSED` in both the block report and [roadmap.md](roadmap.md)

Two rules make the checklist meaningful rather than decorative:

- **No criterion may be satisfied by inspection alone.** Each needs a command, an observed output, or a named human observation with a date.
- **Where only a human can verify something** — browser behaviour, a visual check — the report names the observer, the date, the browser and version. It is not written as though a script proved it.

## Documentation update at block closure

Executed in the block's own branch, so documentation and implementation merge together.

```
1. Fill Evidence in docs/blocks/NN-*.md: commit hashes, command output,
   operator observations, each dated.

2. Fill Deviations from plan. If a deviation changes architecture or an
   earlier decision, add a row to docs/reconciliation.md. If it supersedes
   an accepted decision record, write a new ADR; never edit the old one,
   not even its status field.

3. Update docs/roadmap.md: status, acceptance evidence, next block.

4. Update only the active documents the block actually changed:
      architecture.md    components, routing, identity, storage, cost
      application.md     a defect fixed or discovered
      operations/*.md    a procedure, command or verification changed
      lessons.md         reusable operational knowledge produced
   Touch nothing else. A block that edits every document has unclear scope.

5. Run the consistency checks below.

6. Confirm the Definition of Done, then merge.
```

### Consistency checks

No Markdown linting tooling is installed in this environment, so these are run as shell checks and reported with their output:

```bash
# Internal links resolve
python3 - <<'PY'
import os, re
bad = []
for dp, _, fn in os.walk('.'):
    if '.git' in dp.split(os.sep):
        continue
    for f in (x for x in fn if x.endswith('.md')):
        p = os.path.join(dp, f)
        for m in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', open(p, encoding='utf-8').read()):
            t = m.group(1)
            if t.startswith(('http://', 'https://', '#', 'mailto:')):
                continue
            t = t.split('#')[0]
            if t and not os.path.exists(os.path.normpath(os.path.join(dp, t))):
                bad.append(f'{p} -> {m.group(1)}')
print('broken links:', len(bad))
[print(' ', b) for b in bad]
PY

# Referenced repository paths exist
# Block statuses agree between each report and roadmap.md
# Original decision records unchanged
sha256sum docs/decisions/initial/*.md

# No secret introduced
git diff --cached | grep -nEi 'aws_secret_access_key|BEGIN [A-Z ]*PRIVATE KEY|password\s*[:=]\s*\S'
git diff --check
```

## Change control

For a deviation discovered mid-block, before implementing it:

```
1. Describe the proposed deviation in the block report, under Deviations.
2. State the technical reason and the impact on the live demonstration.
3. If an accepted decision is affected, draft the superseding ADR first.
4. Implement on the block branch.
5. Verify, and record the evidence.
6. Commit, merge into dev, update status.
```

The step that is easy to skip is the third. A decision record that is edited after the fact destroys the only evidence of what was believed and when.

## Decision records

[ADR 0001](decisions/initial/0001-record-architecture-decisions.md) established that a record is never edited once accepted, only superseded. That rule is honoured literally, including for status fields.

As a consequence, the original records in [decisions/initial/](decisions/initial/) are preserved byte-for-byte even where implementation contradicted them. Current applicability is tracked separately in [decisions/README.md](decisions/README.md), which is a living index rather than a record.

Records written after the fact carry an explicit `Recorded` field stating that they are retrospective and naming the commits they were reconstructed from. No record is given a date earlier than the day it was written.

## What this process does not do

It has no approval gates, no sign-off matrix and no templates beyond the single block report. For a single-engineer project those would be ceremony. The three things it does enforce are:

- acceptance criteria written before implementation,
- evidence recorded at the time of verification,
- deviations recorded rather than smoothed over.
