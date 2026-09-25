---
name: herdr-worktrees
description: Use when starting new work, renaming a branch, or setting up a repository for the first time inside Herdr — each unit of work gets its own git worktree, opened as its own Herdr workspace, through the `wkt` CLI from herdr-wkt.
---

# Herdr worktrees

Herdr runs each unit of work in its own workspace, and each workspace should be rooted in its own git worktree. You're inside Herdr when `HERDR_PANE_ID` is set.

Create and manage those worktrees with `wkt`. It puts each worktree in the right place, starts a new branch from a freshly fetched default branch, and opens the worktree as a Herdr workspace or updates the one it's in. While `wkt` is available, don't run `git worktree add` or `herdr worktree create` yourself.

`wkt` is the short name of `herdr-wkt`. If only `herdr-wkt` is on `PATH`, use that: the commands are the same. `wkt <command> --help` shows each command's options.

## Start new work

```sh
wkt new -b <branch> [-s <source>] [-n <label>]
```

Run it anywhere in the repository: the main checkout, any worktree, or the top of a `.bare` layout. It takes the first of these that applies:

1. `<branch>` is already checked out in a worktree: it reuses that worktree.
2. The worktree folder for `<branch>` exists: it reuses the folder.
3. `<branch>` exists locally: it adds a worktree for it.
4. `<branch>` exists only on origin: it creates it locally, tracking origin's.
5. Otherwise it fetches `<source>` from origin and creates `<branch>` from it with `--no-track`. `<source>` defaults to the repository's default branch: origin's `HEAD`, else `main` or `master`.

Then it opens the worktree as a Herdr workspace and focuses it. `-n` labels the workspace; without it, Herdr picks a label.

- A new branch doesn't track `<source>`, so push it the first time with `git push -u origin HEAD`.
- Your own shell doesn't move. If you carry on the work yourself, `cd` to the path `wkt` prints.
- If Herdr isn't running, `wkt` still does the git work, warns with the `herdr` command that would open the worktree, and exits 0. Pass that command on to the user.

### Where worktrees go

`wkt` decides. Don't compute or hard-code the path; read it from the output.

- **`.bare` layouts**, where the repository's git directory is `.bare/`: next to `.bare/`, so each branch is a sibling folder.
- **Normal clones**: `$HERDR_WKT_ROOT/<org>/<repo>/<branch>`. `HERDR_WKT_ROOT` defaults to `~/.herdr/worktrees`, the default of Herdr's own `worktrees.directory` setting. `<org>/<repo>` comes from origin's URL, or is `local/<folder name>` without an origin.

A branch with slashes, like `feat/login`, nests: `feat/login/`.

## Rename the current branch

```sh
wkt rename -b <new-branch> [-n <label>] [-y]
```

Run it from inside the worktree. It renames the branch on origin if it was pushed, renames the local branch, moves the worktree folder to match, and points the Herdr workspace at the new folder, labelled with the new branch name unless `-n` says otherwise.

- **Open pull request.** Renaming a branch through git or GitHub's API closes its open PR. `wkt rename` stops when there is one, and without a terminal, as when you run it, it stops unless given `-y`. Don't add `-y` on your own: tell the user the PR would close and ask. To keep the PR open, the user renames the branch in GitHub's web UI, then `wkt rename` brings the local branch, folder and workspace in line.
- Your shell is left in the old folder, which no longer exists. `cd` to the path it prints.
- It refuses to rename the main checkout of a normal clone, a detached `HEAD`, or onto a branch or folder that already exists.

## Set up a repository for the first time

In a new, empty folder:

```sh
wkt setup <repo-url>
```

It clones the repository into `.bare/`, points `.git` at it, and adds a worktree for the default branch. It doesn't open anything in Herdr. Run `wkt new` from that folder to start work.

## Without wkt

If neither `wkt` nor `herdr-wkt` is on `PATH`, tell the user it installs with `brew install wmxscott/tap/herdr-wkt`, then do the same by hand. For a new branch, set `branch`, and `base` if it shouldn't start from the default branch, then run this as one command:

```sh
branch=<branch>
base=
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
    root=${HERDR_WKT_ROOT:-$HOME/.herdr/worktrees}
    worktree="${root/#\~/$HOME}/${org##*[/:]}/${url##*/}/$branch"
fi
git fetch origin "$base" &&
    git worktree add --no-track -b "$branch" "$worktree" "origin/$base" &&
    herdr worktree open --cwd "$common" --path "$worktree" --focus
```

- For a branch that already exists locally, replace the `git fetch` and `git worktree add` lines with `git worktree add "$worktree" "$branch" &&`. For one that exists only on origin, use `git worktree add --track -b "$branch" "$worktree" "origin/$branch" &&`.
- Add `--label <label>` to `herdr worktree open` to label the workspace.
- `--cwd` must be the repository, not a linked worktree, which Herdr refuses. The common git directory works from anywhere in the repository.
- `herdr worktree create` is no substitute: it branches from `HEAD` or `--base` without fetching, and places worktrees without the `<org>` level.
- The block needs an origin. For a repository without one, ask the user where the worktree should go.

Don't rename by hand. Renaming a pushed branch can close its pull request, so ask the user to install herdr-wkt or do it themselves.
