---
name: landing-changes
description: Use when starting work on a branch or worktree, when about to commit, when opening a pull request, or while a pull request's checks are still running — the branch, worktree and PR discipline every change goes through. Mechanics only — it does not judge whether the work is done, review the change, or decide whether a branch should be merged, kept, or discarded.
---

# Landing changes

## Never work directly on the default branch

Every change goes on a branch, in its own worktree, unless the user says otherwise. Use
`wkt new -b <branch>` when `wkt` ([herdr-wkt](https://github.com/wmxscott/herdr-wkt)) is on
`PATH`; otherwise plain git does the same job:

```sh
git worktree add -b <branch> ../<branch> <base>
```

Land through a pull request; never a direct commit to the default branch (`main`,
`master`, whatever this repo calls it).

## A PR isn't done until its gates are green

Opening it isn't the end of the task. Watch its checks to completion and fix what fails
before reporting the work done:

```sh
gh pr checks <n> --watch --fail-fast
```

A required check failing means something real is wrong — fix the underlying issue, don't
bypass or argue with the gate. (If this repo runs the PR-size gate from
`authoring-stacked-plans` as a required check, a failure there means decompose, not
override.)

## Remove a worktree only once nothing is based on it

A branch's worktree outlives its own PR. In a stack, a phase's children are replanted onto
the new base only after that phase merges — deleting a middle phase's worktree or branch
before its children are replanted strands them, and no merge-versus-keep judgement makes
that safe. A periodic sweep of agent-created worktrees carries the same condition: it may
remove one only when it has no unpushed work *and* no unreplanted children.
