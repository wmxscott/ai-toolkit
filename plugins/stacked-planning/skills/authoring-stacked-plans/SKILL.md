---
name: authoring-stacked-plans
description: Use when work is already known to span more than one pull request and has to be decomposed into an ordered stack of them, when a change has passed the PR size cap and is still growing, or when a stack is nearing a fourth PR with no written plan. Covers the decomposition and the plan artifact recording it — not deciding what to build, and not task-level planning inside a single PR.
---

# Authoring a stacked plan

This skill bundles the plan template and two gate scripts. `template.md` and `scripts/` are
relative to the directory holding this `SKILL.md`, not to the repository; below,
`<scripts>` stands for that `scripts/` directory's absolute path.

## The design must already be settled

This skill decomposes work whose shape is known; it has no discovery phase of its own. If
the plan's **Settled** and **Design** sections would be guesses — the approach still open,
the trade-offs unmade — stop, do that discovery first, and come back with the answers. A
decomposition built on an unsettled design is invalidated by its own first PR.

If the discovery produced a document of its own, distill it into this plan's Settled and
Design sections and treat the original as scratch. One live planning artifact only — two is
exactly how the plan and the code drift apart.

## Plans live at `docs/plans/<base36>-slug.md`

The prefix is `Base36(floor(UnixTimestampSeconds))` — the raw Unix seconds, zero epoch —
lowercased and left-padded with `0` to six characters. The slug is hyphenated lower case.
`1788645964` gives `tkww24`, so `docs/plans/tkww24-stacked-planning-composition.md`:

```sh
python3 -c 'import time
n, digits, out = int(time.time()), "0123456789abcdefghijklmnopqrstuvwxyz", ""
while n: n, r = divmod(n, 36); out = digits[r] + out
print((out or "0").rjust(6, "0"))'
```

Three properties are the reason for it. The names sort chronologically as plain text; each
one carries its creation time without a lookup table; and two branches never collide on it
the way they do on a sequence number. Six characters holds until December 2038, after which
names become seven characters and still sort correctly, since a base36 encoding of a larger
number is never shorter.

This path is a convention this skill establishes, not something every repo already has —
if the repo has its own docs layout, agree on a location with the user before writing
anywhere else.

Use `template.md` in this skill for the section-by-section structure. Two sections are
mandatory with no short form: **Stacks and phases** (the decomposition — this is the
entire point of the plan) and **Forest from the trees**, FFTT (challenges the decomposition
against the goal; never empty — put it past the `advisor` tool and record the verdict, or
argue against it yourself and say the advisor was unavailable).

The Drift test you write inside FFTT isn't one-shot — an implementing session (see
`implementing-stacked-plans`) re-asks it against every PR as it lands. Write it to survive
reuse.

## When you need one

**Past 3 stacked PRs, a plan is mandatory.** Write it before the first PR whenever the
phase estimate already exceeds 3. If the estimate was wrong and a fourth PR arrives
without one, stop, write the plan now, then reconcile the **open** PRs against it — amend
or close whichever drifted. Never retrofit a merged PR.

**When a PR's production-line count passes the cap below and the work is still growing:**
stop, tell the user, and either write a plan or at minimum build a task list of stacked
PRs — one task per PR, plan or no plan.

There is no size exception. Decompose: land types, interfaces and stubs first and the
implementations behind them; land data tables separately from the logic that reads them;
land a parser separately from the transport that feeds it. A unit that looks indivisible
is a unit whose seams have not been found yet.

## One stack or two

A stack is a strictly linear chain of PRs. Work that genuinely forks needs a second stack,
and a second stack is only safe when it is independent:

> Two stacks are independent if landing them **in either order** produces the same result.

Not "they feel unrelated". The phrasing exists to force naming what each stack touches,
which is what makes the check mechanical rather than a judgement call. Each stack block in
the plan carries `Base`, `Owns`, `Independent of` and `Depends on`; `Owns` is the path list
the independence claim is made against, and `template.md` fixes its format because
`stack_overlap.py` parses it.

**The claim is checkable, not just assertable.** That script reads the `Owns` fields out of
the plan and fails a branch that changes a path another stack owns:

```sh
python3 <scripts>/stack_overlap.py origin/<base> --stack A
python3 <scripts>/stack_overlap.py origin/<base> --stack A \
  --plan docs/plans/<this plan>            # when the repo holds more than one live plan
```

Exit `1` — the change reaches into another stack's `Owns`; the stacks are not independent,
and it is the decomposition that is wrong. Exit `2` is not a pass: it could not measure,
usually because a stack block has no `Owns`, carries two, or has an entry that is not a
single backticked glob. An implementing session runs this per PR, so run it once from the
branch carrying the plan to confirm the blocks parse before anyone depends on them.
`<scripts>/STACK_OVERLAP.md` has the glob semantics.

**A shared surface is its own stack.** If two stacks both need to change the same interface
or type, that is not two stacks — it is a third stack that lands first and both rebase
onto. A stack that owns a shared seam is a dependency, not a peer.

When the answer is one stack, say so and say which split you rejected and why. Otherwise a
later session re-opens the decomposition on the same bad seam.

## The PR size gate

`<scripts>/diff_census.py` is the single source of truth for the caps and the exclusions.
It declares its own dependencies inline, so run it through [uv](https://docs.astral.sh/uv/)
— `python3` in front of it fails for want of them:

```sh
uv run --script <scripts>/diff_census.py --format text
uv run --script <scripts>/diff_census.py --base origin/<parent> --format text
```

`--base` defaults to the repository's default branch, which is the wrong answer anywhere
above the bottom of a stack. **Name the parent branch.**

**400 production-line changes, 1200 all-in.** Additions plus deletions. The caps and the
buckets are this repo's `[diff_census]` configuration rather than anything built into the
script; `--print-config` shows the one in force and `--explain` shows how a given file was
classified. The script reads `$STACKED_PLANNING_CONFIG`, else
`.agents/plugins/stacked-planning/config.toml` at the repository's toplevel. With neither,
it only counts and never fails — so in a repo without one, pass
`--config <scripts>/config.example.toml`, which carries the caps above, and suggest the
user commit a copy of it at that path.

Generated and vendored files and general documentation are `exempt` — outside both counts.
Tests and fixtures, and the plan artifact itself, are outside the production budget only,
and still counted in the all-in total. `docs/plans/**` is deliberately carved out of the
general-documentation exemption for this reason: editing the plan still counts.
`<scripts>/DIFF_CENSUS.md` has the buckets, the facets a rule can match on, and where the
comment heuristic misfires.

Three things about the counting are worth knowing before a number surprises you:

- **The comparison is three-dot.** A branch is measured from its merge base with the base
  ref, so commits that landed on the base after the branch started are not charged to it.
  A branch whose base has moved therefore reads lower than a direct comparison of the two
  refs would. `--two-dot` asks for the direct comparison.
- **Comments leave the production budget, not the all-in total.** A line that is only a
  comment, or that ends in one, is outside `production` and still inside `total` — so a
  block of commentary raises the all-in number while leaving the production number alone.
  That is configuration, not a property of the tool.
- **`total` is net of the exemptions.** Lockfiles, vendored trees, minified output and
  general documentation are charged to `exempt`, which is outside the all-in total
  entirely rather than merely outside the production budget.
- **Comments are identified by lexing the file, not by matching the start of a line.** A
  `#` inside a string is code, a shebang is code, and the middle of a block comment is a
  comment even though nothing on that line opens one. So the comment count is usually
  higher than a line-by-line reading of the diff suggests, and the production number
  correspondingly lower. A language with no lexer is counted in full rather than guessed
  at, and appears in the diagnostics.

There's a 10% grace band: the gate warns between the cap and +10%, and only fails past it.
The band is there so a PR a few lines over isn't forced into a contrived split — it does
not move where decomposition starts. That still fires at 400, not at 440.

Exit codes: `0` pass or warn, `1` past the hard limit, `2` couldn't measure. A pre-push
hook or CI check can run this directly.
