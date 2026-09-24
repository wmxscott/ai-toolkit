---
name: stacked-planning
description: Use only when work will land as more than one pull request and it is genuinely unclear whether to write the stacked plan or execute one that already exists — a router between authoring-stacked-plans and implementing-stacked-plans. Not a general entry point for planning or design, and not for a change that fits in one PR.
---

# Stacked planning

A router, not a workflow. Three cases:

1. **No plan artifact exists yet for this work.** Go to `authoring-stacked-plans` —
   write `docs/plans/<base36>-slug.md` before the first PR.
2. **A plan artifact already exists** (`docs/plans/<base36>-slug.md`) and the user is pointing
   at it, naming one of its stacks or phases, or asking to implement, execute, or
   continue it. Go to `implementing-stacked-plans`.
3. **Mid-implementation, no plan was ever written**, and the PR-size gate just fired or a
   fourth stacked PR is about to happen without one. Stop. Go to `authoring-stacked-plans`
   now — write the plan retroactively, then reconcile the **open** PRs against it. Merged
   PRs are history; never retrofit them.

Every change in a stack still lands through the ordinary discipline in `landing-changes`
(branch, worktree, PR — never a direct commit to the default branch) — that applies
whether or not a plan exists.
