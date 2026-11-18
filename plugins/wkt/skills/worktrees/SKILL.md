---
name: worktrees
description: Use when starting new work, renaming a branch, removing a finished worktree, or setting up or converting a repository — each unit of work gets its own git worktree through the `wkt` CLI, opened as a tmux session or Herdr workspace only when the user asks.
---

# Worktrees

Each unit of work gets its own git worktree, so parallel work can't trip over one checkout. Create and manage them with `wkt`. It puts each worktree in the right place and starts a new branch from a freshly fetched default branch. While `wkt` is available, don't run `git worktree add`, `git worktree remove` or `herdr worktree create` yourself.

This describes wkt 2.0 and later. `wkt <command> --help` shows each command's options.

## Nothing opens unless asked

`wkt new` makes or reuses the worktree and prints its path. It opens nothing unless given one of these:

- `--tmux` opens the worktree as its own tmux session. Inside tmux, it switches the user's tmux client to that session, which moves their screen. Outside tmux, it prints how to attach.
- `--herdr` opens it as a [Herdr](https://herdr.dev) workspace and focuses it.

A session or workspace is a new place for someone to work, not something you need to work in a worktree yourself.

- **Run plain `wkt new -b <branch>` by default**, including when you create a worktree to do the work yourself from this session.
- **Add `--tmux` or `--herdr`** only when the user asks for the work opened that way. Never pass `--tmux` unprompted: inside tmux, it takes over the user's screen.

## Start new work

```sh
wkt new -b <branch> [-s <source>] [-n <name>] [--tmux | --herdr]
```

Run it anywhere in the repository: the main checkout, any worktree, or the top of a `.bare` layout. It takes the first of these that applies:

1. `<branch>` is already checked out in a worktree: it reuses that worktree.
2. The worktree folder for `<branch>` exists: it reuses the folder.
3. `<branch>` exists locally: it adds a worktree for it.
4. `<branch>` exists only on origin: it creates it locally, tracking origin's.
5. Otherwise it fetches `<source>` from origin and creates `<branch>` from it with `--no-track`. `<source>` defaults to the repository's default branch: origin's `HEAD`, else `main` or `master`.

It then prints the worktree's path. With `--tmux` or `--herdr`, it also opens the worktree as above. With `--tmux`, `-n` names the session instead of `<repo>/<branch>`. With `--herdr`, it labels the workspace; without it, Herdr picks a label.

- A new branch doesn't track `<source>`, so push it the first time with `git push -u origin HEAD`.
- Your own shell doesn't move. `cd` to the path `wkt` prints to work there.
- If tmux or Herdr can't open the worktree when asked, `wkt` still does the git work, warns, and exits 0. Pass the warning on to the user.

### Where worktrees go

`wkt` decides. Don't compute or hard-code the path; read it from the output.

- **`.bare` layouts**, where the repository's git directory is `.bare/`: next to `.bare/`, so each branch is a sibling folder.
- **Normal clones**: `$WKT_ROOT/<org>/<repo>/<branch>`. `WKT_ROOT` defaults to `~/.herdr/worktrees`, the default of Herdr's own `worktrees.directory` setting. `<org>/<repo>` comes from origin's URL, or is `local/<folder name>` without an origin.

A branch with slashes, like `feat/login`, nests: `feat/login/`.

## Rename the current branch

```sh
wkt rename -b <new-branch> [-n <name>] [-y]
```

Run it from inside the worktree. It renames the branch on origin if it was pushed, renames the local branch and moves the worktree folder to match. If the worktree has a Herdr workspace, it points it at the new folder, labelled with the new branch name. If it has a tmux session, it renames it to `<repo>/<new-branch>`. `-n` sets that label and name instead. It never opens a workspace or session that wasn't there, so it needs no flag for either.

- **Open pull request.** Renaming a branch through git or GitHub's API closes its open PR. `wkt rename` stops when there is one, and without a terminal, as when you run it, it stops unless given `-y`. Don't add `-y` on your own: tell the user the PR would close and ask. To keep the PR open, the user renames the branch in GitHub's web UI, then `wkt rename` brings the local branch, folder, workspace and session in line.
- Your shell is left in the old folder, which no longer exists. `cd` to the path it prints.
- It refuses to rename the main checkout of a normal clone, a detached `HEAD`, or onto a branch or folder that already exists.

## Remove a finished worktree

```sh
wkt rm [-b <branch>] [-f]
```

Without `-b`, it removes the worktree you're in. With `-b`, it removes the one that has `<branch>` checked out, from anywhere in the repository. It removes the folder, closes the worktree's tmux session and Herdr workspace if it has them, and deletes the local branch only when nothing on it would be lost: the default branch already has it, or its pull request was merged with all of its commits, squash merges included. Otherwise it keeps the branch and says why. It never touches the branch on origin.

- **Your own merged work.** Once the pull request for a worktree you made is merged, you may remove it with `wkt rm -b <branch>`. `cd` out of it first, to the main checkout for example, so your shell isn't left in a folder that no longer exists.
- **Never pass `-f`** unless the user asks. `wkt rm` refuses uncommitted changes, untracked files and commits that were never pushed, and it refuses the main checkout and the default branch's worktree. When it refuses, report why to the user; don't force it or work around it.
- If this session runs inside the worktree's tmux session or Herdr workspace, removing it closes them and ends this session. Leave that one to the user.

```sh
wkt rm --merged [-y]
```

It removes every worktree in the repository whose branch nothing would be lost from, by the same test, and skips any with uncommitted changes or untracked files. Run it only when the user asks for a cleanup. Run it first without `-y`: with no terminal to ask on, it lists what it would remove and skip, then stops with nothing changed. Show the user that list, and add `-y` only once they agree.

## Set up a repository

In a new, empty folder:

```sh
wkt setup <repo-url>
```

It clones the repository into `.bare/`, points `.git` at it, and adds a worktree for the default branch. It opens no session or workspace. Run `wkt new` from that folder to start work.

To convert a clone that already exists into the same layout, run this at its top:

```sh
wkt adopt
```

It moves `.git` to `.bare/` and the working tree, uncommitted changes included, into a folder named after the current branch. Every path in the clone changes, so run it only when the user asks for it.

## Without wkt

If `wkt` isn't on `PATH`, tell the user it installs with `brew install wmxscott/tap/wkt`, then do the same by hand. For a new branch, set `branch`, `base` if it shouldn't start from the default branch, and `open_in_herdr=1` only if the user asks for the work opened as a Herdr workspace, then run this as one command:

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

To remove your own worktree once its pull request is merged, run `git worktree remove <path>` from outside it. Don't add `--force` unless the user asks, and leave the branch for the user to delete.
