---
name: implementing-stacked-plans
description: Use when a plan in docs/plans/ already defines its work as stacks of PRs and the user asks to implement, execute, or continue it, or names one of its stacks or phases — orchestrates one subagent per PR in its own worktree, reviewing and landing each before dispatching the next. Orchestration above the PR boundary only — everything inside a single PR — its tests, its debugging, its review — belongs to the subagent doing it. Not for writing a new plan; see authoring-stacked-plans.
---

# Implementing a plan as stacks of PRs

You are the **orchestrator**, not the author. Subagents write the code; you decide what
gets dispatched, you review what comes back, and you own the stacks. Writing production
code yourself is the failure mode this skill exists to prevent — it burns the one context
that has to survive the whole plan. If the agent cannot spawn subagents, the same shape
holds with one fresh session per PR, briefed as below.

The gate scripts ship with the `authoring-stacked-plans` skill. Below, `<scripts>` stands
for the absolute path of its `scripts/` directory: `../authoring-stacked-plans/scripts`,
resolved against the directory holding this `SKILL.md`.

## Before dispatching anything

1. **Read the plan end to end** — `docs/plans/<base36>-slug.md`, all of it, not just
   Stacks and phases. Settled is the "do not re-derive" section, there to stop you paying
   for the same discovery twice. The Design sections are the contract the code must match.
   Forest from the trees — FFTT — is the standard every PR gets judged against.
2. **Re-read Stacks-and-phases and FFTT together.** The former is the implementation
   shape: one or more **stacks**, each a linear chain of PRs, in dependency order. The
   latter says what that sequence is *for* — and its Drift test is what you'll re-ask per
   PR below. A PR that satisfies the phase list and fails the drift test is a PR to send
   back.
3. **Map the stacks before you touch anything** — which exist, how many phases each
   holds, which stack depends on which, and which (if any) the plan explicitly says can
   run at once. That map is what you orchestrate against.
4. **Ask clarifying questions now**, before the first dispatch. Ambiguity that reaches a
   subagent comes back as code built on a guess. Ambiguity resolved here costs one
   message.
5. **Open the ledger and the todo list** (below) before dispatch #1.
6. **State your understanding back and wait.** Restate the stacks, their order, and which
   phase you are starting with, then get the go-ahead. This is a gate, not a courtesy — it
   is the last cheap moment to catch a misread plan.

Invoked with no plan named, list `docs/plans/` and ask which one. Never guess.

## The ledger

A compaction must never cost a re-dispatch. Keep a ledger file outside the repository — in
the session scratchpad if the agent has one — named `ledger.md`, and update it the moment a
phase changes state, not at the end of the turn.

Two tables. The stack table is the whole picture at a glance, and the one thing worth
restating from the plan: a context that has just compacted should read the state of the
world, not infer it from phase rows.

```markdown
| Stack | Base | Owns | State | Active phase |
|---|---|---|---|---|
| A | main | `src/auth/**` | active | A2 |
| B | main | `src/billing/**` | active | B1 |
| C | A | `src/auth/ui/**` | blocked on A | — |
```

States: `not started` → `active` → `parked` → `landed`; a stack waiting on another says so
instead. Two `active` rows are the cap made visible.

The phase table tracks *execution*, not the plan's own shape — the stack a phase belongs
to, its base, and what it depends on already live in the plan's Stacks-and-phases table,
so it only needs the phase id to join against them:

```markdown
| Phase | Branch | Worktree | GH | State |
|---|---|---|---|---|
| A1 | feat/auth_scheme_records | ../feat/auth_scheme_records | #182 | merged |
| A2 | feat/auth_scheme_backfill | ../feat/auth_scheme_backfill | #183 | in review |
| B1 | … | — | — | not started |
```

States: `not started` → `dispatched` → `in review` (you are reading the diff) → `PR open`
→ `merged` / `sent back`.

Mirror the same rows into the task-tracking todo tool — the todo list is what you steer by
in-session, the ledger is what a fresh context reads.

**The moment a phase merges, append one line to the plan's own `Log` section** —
`YYYY-MM-DD — phase A2 landed as #183` — before moving on. The ledger dies with the
session; the plan's Log is what a later session, or a different person, has to go on.
Keep per-PR execution detail (branch names, worktree paths, review notes) in the ledger
only — the Log stays one line per landed phase or amendment.

Every PR in a stack carries that stack's checklist, copied verbatim from its
Stacks-and-phases block in the plan, differing only in which boxes are ticked. That is the
third copy, and the one reviewers and future sessions see.

## One PR, one subagent, one worktree

One worktree per PR, based on the **previous phase's branch**, not the default branch — a
stack is strictly linear, one parent, one child. The first phase of a stack is based on
the plan's stated base for that stack. See `landing-changes` for how a worktree actually
gets created — this skill has no opinion on branch naming; use whatever this repo's
convention is.

Dispatch one subagent per PR, sequentially within a stack. Two stacks run at once only
where the plan explicitly says they are independent; that is what makes them separate
stacks rather than one — stacks cannot branch. Finish or park a stack deliberately, and
record which one you are on in the ledger.

### What the subagent gets — and nothing else

Context pollution is the other failure mode. The subagent gets exactly what it needs to
land its one PR:

- Its worktree path, its branch, and its base branch.
- The plan path, and **the specific phase block** (its Lands / Shippable when / Split
  seam) quoted in the brief.
- The Settled atoms and Design subsections that PR actually touches, cited by id (`S3`,
  `S7`) rather than the whole section.
- The phase's *Shippable when* condition, restated as its acceptance criteria.
- The instruction to build the phase **test-first** — a failing test, then the code that
  passes it.
- How to run the size gate, with `<scripts>` spelled out, since the subagent has not
  loaded this skill:
  `uv run --script <scripts>/diff_census.py --base origin/<base-branch> --format text`.
  Name the base: it defaults to the repository's default branch, which is the wrong
  answer anywhere above the bottom of a stack. The comparison is three-dot, comments sit
  outside the production budget and inside the all-in total, and exempt lines are outside
  both.

It does **not** get: your transcript, other phases' briefs, the review notes from earlier
PRs, or "read the whole plan and figure out your part." If a fact from an earlier PR
matters, state the fact in the brief — do not hand over the history that produced it.

It also does **not** spawn subagents of its own. Orchestrator → PR-subagent →
task-subagent is three levels deep for one PR's worth of work; test-first inside the phase
is enough.

Tell it to stop and report rather than improvise when the plan is wrong or silent. A
subagent that invents a design decision has cost more than one that blocks.

### Two stacks at once

**Two in flight, maximum.** Subagents parallelize; you do not — you read every diff, run
the gates and ask the drift test one at a time, in the single context that has to survive
the whole plan. So this is pipelining, not concurrency: it overlaps stack B's execution
with stack A's review. Real, but bounded — which is why the cap is small.

**Dispatch into the other stack only while reviewing this one.** Never two open diffs.

**Peers are not replanted.** When stack A lands to the default branch, do **not** replant
stack B. Independence means A's landing does not affect B; eager replanting invalidates
open PRs and forces re-review for nothing. Replant B only when a later B phase genuinely
needs something A landed, or when B's bottom PR reports a conflict at land time. Otherwise
let B run behind and rebase once, at the end.

**The recovery path**, decided now rather than at the worst moment — when the overlap gate
fires mid-flight: park the later stack → land the earlier one → replant the parked stack
on the new default branch → re-run the overlap gate before resuming. That is most of what
`parked` is a ledger state for.

## Reviewing what comes back

Never take a subagent's word for it. For each returned PR:

1. Read the diff yourself, in its worktree.
2. Check it against the Design sections it cites (does it match the contract?) and its
   phase block (is it this phase, all of it, and nothing from the next one?).
3. Run the size gate against the base branch — over the cap means split at the seam the
   phase block names, not lean on the grace band.
4. **While a second stack is active, run the overlap gate beside it:** `python3
   <scripts>/stack_overlap.py origin/<base-branch> --stack <this stack's id>`. Exit 1 means this PR reaches into the other stack's `Owns` paths —
   take the recovery path (*Two stacks at once*) rather than merging across the seam.
   Exit 2 is not a pass: it could not measure, so fix the
   plan's stack blocks or pass `--owns` before believing any verdict. See
   `<scripts>/STACK_OVERLAP.md` for the glob semantics and the gate's known limits.
5. **Ask the plan's own Drift test** (FFTT) against this specific PR. If the answer isn't
   clearly fine and the advisor is available, put it past advisor too and record what it
   said in the ledger row. This is the check that catches PRs that are individually
   correct and collectively pointless. While a second stack is active, ask it across
   stacks too — *do A and B together still serve the plan's Goal?* B was worth doing
   when the plan was written; A's actual shape may since have made it unnecessary.
6. Send it back with specific, narrow feedback rather than fixing it yourself. Re-dispatch
   to the same subagent when the context is still alive; a fresh one gets a fresh brief
   plus the exact defect.

## Landing it

Non-interactive `gh stack` basics — full command reference is the `gh-stack` skill (ships
with the [gh-stack](https://github.com/github/gh-stack) extension; if a command exits 9 or
reports unknown, `gh extension install github/gh-stack`):

```sh
gh pr create --base <parent-branch> --title '...' --body '...'   # titled per this repo's own convention
gh stack link <phase-1> <phase-2> <phase-3>   # this stack's order, bottom to top
gh stack link <stack-number> <phase-4>        # append a later phase to a live stack
```

`link` takes branch names, PR numbers or PR URLs, pushes what needs pushing, and points
each base at the one below — no local tracking state needed, so it works from any
worktree. **Do not use `gh stack submit --auto`** — it titles PRs from commit subjects,
not this repo's convention. Never run `gh stack view` or `gh stack checkout` bare — always
`--json`, always with an argument — see the `gh-stack` skill for why.

Without the extension, and if the user would rather not install it, open each PR with
`gh pr create --base <parent-branch>` alone and replant by hand as below: the stack is
still linear, it just isn't linked on GitHub.

Each stack is linked separately — never link PRs from two stacks into one chain.
**Replanting is parent→child, within one stack:** after a parent squash-merges, replant
its child before dispatching anything on top of it (`gh stack sync` does this
automatically; by hand, parent-first: `git rebase --onto <default-branch> <old-parent-tip>
<child-branch>`). A peer stack is never replanted for it — see *Two stacks at once*.
Update the ledger, append to the
plan's Log, and update the checklist boxes in every open PR in that stack.

Then see `landing-changes` — a PR here is not done until its gates are green.

## Rules that do not bend

- **You orchestrate; subagents author.** Your edits are limited to PR bodies, the ledger,
  and the plan itself.
- **Phase boundaries are PR boundaries.** Never let one PR carry two phases because they
  were "small."
- **Stacks are linear.** Work that genuinely forks needs a second stack, not a branching
  phase.
- **Two stacks in flight, one open diff.** The cap is on you, not on the subagents.
- **The plan is the source of truth.** If implementation shows the plan is wrong, stop,
  amend the plan artifact, and say so — do not let the code and the plan silently diverge.
- **Never work on the default branch** — see `landing-changes`.
