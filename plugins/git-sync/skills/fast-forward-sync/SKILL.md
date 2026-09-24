---
name: fast-forward-sync
description: Use when starting work on a task inside a git repository — checks whether the current branch is behind its upstream and can be fast-forwarded without conflicts, and fast-forwards it before any work begins.
---

# Fast-forward sync

Starting work on a stale branch risks conflicts, duplicated fixes, or reviewing code against an outdated base. Before starting a task in a git repository, check whether the current branch has an upstream, is behind it, and can be fast-forwarded cleanly. If it can, fast-forward it before touching any files.

## When to use

At the start of a task or session in a git repository, before making edits or running other git commands. Skip it when the repository has no remote or the current branch has no upstream.

## Procedure

### 1. Does the branch have an upstream?

```bash
git rev-parse --abbrev-ref --symbolic-full-name '@{u}'
```

An error means no upstream is configured, or `HEAD` is detached. There is nothing to sync against: carry on with the task.

### 2. Update the remote-tracking refs

```bash
git fetch
```

This only updates remote-tracking refs such as `origin/main`. It never touches the working tree or the local branch. If it fails (offline, no credentials), tell the user the branch could not be checked and carry on.

### 3. Compare the branch with its upstream

```bash
git rev-list --left-right --count 'HEAD...@{u}'
```

The output is `<ahead>	<behind>`:

- `0	0`: up to date.
- `0	N`: behind only. Safe to fast-forward.
- `N	0`: ahead only. Nothing to pull.
- `N	M`: diverged. Don't fast-forward. Tell the user the branch has diverged and let them choose between merge and rebase; don't guess.

### 4. Fast-forward if behind only

```bash
git merge --ff-only '@{u}'
```

`--ff-only` is the safety net. If a true fast-forward isn't possible, because history has diverged or uncommitted changes would be overwritten, git refuses and leaves the working tree untouched. It never creates a merge commit or clobbers anything. Don't stash or stage first: let git refuse if it must, and report why.

## Quick reference

| Ahead / behind | Action |
|---|---|
| No upstream | Skip: nothing to sync |
| 0 / 0 | Up to date, carry on |
| 0 / N | `git merge --ff-only '@{u}'` |
| N / 0 | Ahead of upstream, nothing to pull |
| N / M | Diverged: don't merge, tell the user |

## Common mistakes

- **Running `git pull`.** Depending on `pull.rebase` and `pull.ff`, it can create a merge commit or rebase local work without asking. `git fetch` plus `git merge --ff-only '@{u}'` gives either a clean fast-forward or a safe no-op.
- **Comparing against a stale remote-tracking ref.** Always `git fetch` first, or the branch can look up to date when the remote has moved.
- **Forcing a sync when diverged.** Never replace a failed fast-forward with `git reset --hard '@{u}'`: it discards local commits. Diverged history means asking the user.

`'@{u}'` is quoted so the commands work unchanged in PowerShell, where a bare `@{...}` is a hashtable.
