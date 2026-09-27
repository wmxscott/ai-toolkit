---
name: worktrees
description: Use when starting new work, renaming a branch, or setting up or converting a repository — each unit of work gets its own git worktree through the `wkt` CLI, opened as a Herdr workspace only when a separate workspace is wanted.
---

# Worktrees

Each unit of work gets its own git worktree, so parallel work can't trip over one checkout. Create and manage them with `wkt`. It puts each worktree in the right place and starts a new branch from a freshly fetched default branch. While `wkt` is available, don't run `git worktree add` or `herdr worktree create` yourself.

`wkt <command> --help` shows each command's options.

## Herdr workspaces are opt-in

Inside [Herdr](https://herdr.dev) (`HERDR_TAB_ID` is set), `wkt new` and `wkt rename` also open the worktree as a Herdr workspace, unless given `--no-herdr`. A new workspace is a new place for someone to work, not something you need to work in a worktree yourself.

- **Pass `--no-herdr` by default**, including when you create a worktree to do the work yourself from this session.
- **Leave it off** only when a separate Herdr workspace is the point: the user asks for one, or the work is meant to carry on there, in another session or by the user.

Outside Herdr, `wkt` never talks to it, and `--no-herdr` changes nothing.

## Start new work

```sh
wkt new -b <branch> [-s <source>] [-n <label>] [--no-herdr]
```

Run it anywhere in the repository: the main checkout, any worktree, or the top of a `.bare` layout. It takes the first of these that applies:

1. `<branch>` is already checked out in a worktree: it reuses that worktree.
2. The worktree folder for `<branch>` exists: it reuses the folder.
3. `<branch>` exists locally: it adds a worktree for it.
4. `<branch>` exists only on origin: it creates it locally, tracking origin's.
5. Otherwise it fetches `<source>` from origin and creates `<branch>` from it with `--no-track`. `<source>` defaults to the repository's default branch: origin's `HEAD`, else `main` or `master`.

Without `--no-herdr`, inside Herdr, it then opens the worktree as a Herdr workspace and focuses it. `-n` labels the workspace; without it, Herdr picks a label.

- A new branch doesn't track `<source>`, so push it the first time with `git push -u origin HEAD`.
- Your own shell doesn't move. `cd` to the path `wkt` prints to work there.
- If Herdr isn't reachable when a workspace was wanted, `wkt` still does the git work, warns with the `herdr` command that would open the worktree, and exits 0. Pass that command on to the user.

### Where worktrees go

`wkt` decides. Don't compute or hard-code the path; read it from the output.

- **`.bare` layouts**, where the repository's git directory is `.bare/`: next to `.bare/`, so each branch is a sibling folder.
- **Normal clones**: `$WKT_ROOT/<org>/<repo>/<branch>`. `WKT_ROOT` defaults to `~/.herdr/worktrees`, the default of Herdr's own `worktrees.directory` setting. `<org>/<repo>` comes from origin's URL, or is `local/<folder name>` without an origin.

A branch with slashes, like `feat/login`, nests: `feat/login/`.

## Rename the current branch

```sh
wkt rename -b <new-branch> [-n <label>] [-y] [--no-herdr]
```

Run it from inside the worktree. It renames the branch on origin if it was pushed, renames the local branch and moves the worktree folder to match. Inside Herdr it also points the Herdr workspace at the new folder, labelled with the new branch name unless `-n` says otherwise. Pass `--no-herdr` when the worktree has no workspace of its own, so a rename doesn't open one.

- **Open pull request.** Renaming a branch through git or GitHub's API closes its open PR. `wkt rename` stops when there is one, and without a terminal, as when you run it, it stops unless given `-y`. Don't add `-y` on your own: tell the user the PR would close and ask. To keep the PR open, the user renames the branch in GitHub's web UI, then `wkt rename` brings the local branch, folder and workspace in line.
- Your shell is left in the old folder, which no longer exists. `cd` to the path it prints.
- It refuses to rename the main checkout of a normal clone, a detached `HEAD`, or onto a branch or folder that already exists.

## Set up a repository

In a new, empty folder:

```sh
wkt setup <repo-url>
```

It clones the repository into `.bare/`, points `.git` at it, and adds a worktree for the default branch. It never opens anything in Herdr. Run `wkt new` from that folder to start work.

To convert a clone that already exists into the same layout, run this at its top:

```sh
wkt adopt
```

It moves `.git` to `.bare/` and the working tree, uncommitted changes included, into a folder named after the current branch. Every path in the clone changes, so run it only when the user asks for it.

## Without wkt

If `wkt` isn't on `PATH`, tell the user it installs with `brew install wmxscott/tap/wkt`, then do the same by hand. For a new branch, set `branch`, `base` if it shouldn't start from the default branch, and `open_in_herdr=1` only if a Herdr workspace is wanted, then run this as one command:

```sh
branch=<branch>
base=
open_in_herdr=
common=$(git rev-parse --path-format=absolute --git-common-dir)
if [ -z "$base" ]; then
    base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD) || base=main
    base=${base#origin/}
fi
if [ "$(basename "$common")" = .bare ]; then
    worktree="$(dirname "$common")/$branch"
else
    url=$(git remote get-url origin)
    url=${url%.git}
    org=${url%/*}
    root=${WKT_ROOT:-$HOME/.herdr/worktrees}
    worktree="${root/#\~/$HOME}/${org##*[/:]}/${url##*/}/$branch"
fi
git fetch origin "$base" &&
    git worktree add --no-track -b "$branch" "$worktree" "origin/$base" &&
    if [ -n "$open_in_herdr" ]; then
        herdr worktree open --cwd "$common" --path "$worktree" --focus
    fi
```

- For a branch that already exists locally, replace the `git fetch` and `git worktree add` lines with `git worktree add "$worktree" "$branch" &&`. For one that exists only on origin, use `git worktree add --track -b "$branch" "$worktree" "origin/$branch" &&`.
- Add `--label <label>` to `herdr worktree open` to label the workspace.
- `--cwd` must be the repository, not a linked worktree, which Herdr refuses. The common git directory works from anywhere in the repository.
- `herdr worktree create` is no substitute: it branches from `HEAD` or `--base` without fetching, and places worktrees without the `<org>` level.
- The block needs an origin. For a repository without one, ask the user where the worktree should go.

Don't rename by hand. Renaming a pushed branch can close its pull request, so ask the user to install `wkt` or do it themselves.
