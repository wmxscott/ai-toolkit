# Plan template

Copy this into `docs/plans/<base36>-slug.md` and fill it in — see `SKILL.md` for how the
base36 prefix is formed. Mandatory/droppable status is
marked per section. Two sections are mandatory with no short form: **Stacks and phases**
and **Forest from the trees**, FFTT below — see `SKILL.md` for why.

````markdown
# Plan — Title

| | |
|---|---|
| **Status** | draft · in progress · landed · abandoned — and if in progress, the next phase id |
| **Updated** | YYYY-MM-DD |
| **Tracker** | issue ref or URL, or `—` |
| **Related** | other plans, ADRs, docs, PRs, external links |

Keep the header to four rows. `Updated` is the last-amended date — the creation date is
already in the filename's base36 prefix. `Status` carries the next phase id when in progress (`in progress · next: B1`) so a
resuming session reads current state without parsing the whole file — that id is derived
from the last `Log` entry, and `Log` wins if the two ever disagree. Use `abandoned` rather
than deleting a dropped plan.

## Goal

**Mandatory, one paragraph, no more.** What changes, for whom, and why now. Write one
falsifiable sentence that a single PR can be held against — this is the sentence the FFTT
drift test is run against, so vagueness here disables the drift check downstream. No
mechanism, no steps.

### Done when

**Mandatory.** A checklist of conditions that are true when the whole plan is finished,
each one something a later session can actually run or observe. At least one must check
against a real running system — a request served, a record written, a metric visible in
the dashboard — not a passing test suite. This answers *is the goal met*, which is a
different question from whether any individual PR is shippable.

## Settled — do not re-derive

**Mandatory.** Numbered atomic entries, `S1`, `S2`, …, so a later session or a subagent
brief can cite one without quoting the section. Ids are append-only: never renumber, and
strike an entry that turns out wrong rather than deleting it. Each entry is one of:

- **A fact** — the claim, and how it is known (file path, measurement, doc link, person).
- **A decision** — what was decided, what was rejected, and why. The rejected alternative
  is the load-bearing part: a later session re-opens a settled argument far more
  expensively than it re-measures a number.

Keep the fact and the decision it forces in the same entry when they are one chain of
reasoning. Include what a later session would otherwise spend a day rediscovering,
including dead ends and things that turned out not to exist. Short is fine when genuinely
little was discovered; never delete the header.

## <Design section — named for its subject>

**Mandatory as a group; use as many sections as the subject needs.** Do not write one
section called "Design". Write the sections the mechanism actually has, each named for
what it covers — "Record shapes", "Failure semantics", "Event catalog", "Sequence".
Number them if you want intra-plan cross-references. Across all of them, cover: the
shapes and contracts the code must match, the sequence of operations, and what happens
when each step fails. Anything a PR could plausibly implement two different ways belongs
here or in Settled, decided.

Break each design section into `###` subsections, one per contract or mechanism, named for
what it specifies. A phase block cites the subsection it needs, so a subagent brief hands
over one contract rather than a whole section — a section that is one long prose block
cannot be cited at useful granularity.

## Stacks and phases

**Mandatory. No short form. This section is the point of the plan.**

One phase = one PR, sized to pass the repo's size gate. If the work does not decompose
into phases, the plan is too big — split the plan, do not widen the phases. A **stack** is
a strictly linear chain of PRs, each based on the previous one; work that genuinely forks
needs a second stack, not a branching phase.

For each stack, give a heading with its id and name, then the four independence fields,
then the map, then one block per phase. Two stacks may be implemented concurrently **only
if this section says so explicitly** — silence means sequential.

### Stack A — <name>

- **Base:** `main`
- **Owns:** `src/billing/**`, `migrations/2026*_billing_*.sql`
- **Independent of:** B
- **Depends on:** —

Two stacks are independent if landing them **in either order** produces the same result.
Not "they feel unrelated" — the phrasing forces naming what each stack touches, which is
what makes the check mechanical rather than a judgement call. If two stacks both need to
change the same interface or type, that is not two stacks: it is a third stack that lands
first and both rebase onto. A stack that owns a shared seam is a dependency, not a peer.

The four fields are the authoritative statement of that, so do not repeat the base or the
independence claim in the heading. `Owns` is parsed by `stack_overlap.py`, which checks the
independence claim rather than trusting it — a data field, not prose. Format, exactly:

- All four fields, in that order, one `- **<Field>:** <value>` bullet each, between the
  stack heading and the phase table.
- `Base` — one branch name in backticks: `` `main` ``, or the head branch of the stack
  this one is stacked on.
- `Owns` — the paths this stack may change: comma-separated glob patterns, each in
  backticks, relative to the repo root, `**` matching across directories. Exactly one
  `Owns` field per stack; if the value is too long for one line, wrap it onto continuation
  lines indented two spaces — the field ends at the next `- **` bullet or at a blank line.
  No prose and no parentheticals in this field. A stack owning no paths is written `—`,
  and a plan whose stacks all own `—` has not done the independence work.
- `Independent of` / `Depends on` — comma-separated stack ids (`B`, `C`), or `—` for
  none, each optionally followed by a short parenthetical note. Every other stack in the
  plan appears in exactly one of the two.

| Phase | Lands | Depends on |
|---|---|---|
| A1 | one line | — |
| A2 | one line | A1 |

Copyable checklist — implementing sessions paste this into every PR body in the stack,
ticking boxes as phases land:

- [ ] A1 — <name>
- [ ] A2 — <name>

**A1 — <name>**
What lands, concretely enough that a subagent given only this block and the sections it
cites can build it. Cite the Settled ids and design sections it touches (`S3`, `S7`,
Failure semantics) rather than restating them.
*Shippable when:* the gates that make this PR independently mergeable — build, tests,
whatever the repo requires — plus the one observable behaviour that shows this phase did
its job. This is not "the goal is met"; it is "this PR can land on its own."
*Split seam:* if this comes in over the size gate, the named line to split it at. Do not
estimate a change count — the gate measures the real number, and a pre-implementation
guess carries no information. Name the seam instead.

## Forest from the trees

**Mandatory. Never empty, never deferred.** Two required parts.

### Challenge

Put the Stacks-and-phases section past the advisor tool and record what it said, in enough
detail that a later session can tell whether the plan was challenged or rubber-stamped —
then say what you changed in response, or why nothing changed. Nothing-changed is a real
outcome but it is also the rubber-stamp tell, so justify it.

If the advisor is unavailable, say so explicitly and do the work yourself: state the
strongest available case that the phase sequence is *wrong* — that it is steps which each
make sense and collectively miss the Goal — and record what that surfaced. An unavailable
advisor changes who writes this, not whether it gets written.

### Drift test

One or two standing questions, phrased so they can be asked of any *single* PR in the
stack, not just of the plan as a whole. Implementing sessions re-run these per PR, so
write them to survive reuse — a question like "if every remaining phase were cancelled
after this one, what part of the Goal would already be true?" beats a one-time verdict,
and unlike "does this PR move the Goal?" it does not fail a foundation phase that
legitimately lands plumbing with no call sites yet. Write questions that separate
scaffolding with a payoff from scaffolding for its own sake. This is the check that
catches PRs that are individually correct and collectively pointless.

## Not doing

**Droppable for a small plan.** Each item: the thing, and whether it is deferred, out of
scope, or rejected — with the reason. Exists so a later session does not helpfully re-add
what you deliberately cut.

## Blocked on

**Omit if genuinely nothing is blocked.** Each item: what is unresolved, **who or what
resolves it**, and which phase it blocks (or "nothing yet"). Every item names an owner —
a person, a team, an external system, or a decision the user must make. An item with no
owner is not a blocker; if it is a risk you have accepted, record it as a decision in
Settled, and if it is something you chose not to handle, record it in Not doing. Do not
keep a list of unowned worries here.

## Log

**Mandatory header; starts empty.** Append-only, coarse entries only, newest last:

- `YYYY-MM-DD` — phase A2 landed as `<PR or commit ref>`
- `YYYY-MM-DD` — plan amended: `<what changed and what forced it>`

This exists because the implementation ledger lives in the session scratchpad and dies
with the session; a plan that cannot say which phases already landed cannot be resumed.
Per-PR state transitions, branch names, worktree paths, and review notes stay in the
ledger — they do not go here. One line per landed phase and one per amendment.
````
