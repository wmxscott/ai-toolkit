---
name: gh-app-auth
description: Use before committing, pushing or opening a pull request in a GitHub repository, to check whether it is set up to act as a GitHub App bot through the gh-app-auth extension; when asked to make an agent commit or open PRs as a GitHub App in a repository or org; or when git push or gh fails in such a repository with an expired or invalid token, such as "Authentication failed", "Invalid username or token", "HTTP 401 Bad credentials", a JWT or private key error, or a PR or commit that came out under the user's own name.
---

# Acting as a GitHub App

In a repository set up for it, an agent commits, pushes and opens pull requests as a GitHub App's bot (`<slug>[bot]`), through the [gh-app-auth](https://github.com/AmadeusITGroup/gh-app-auth) `gh` extension. There is one app per GitHub account or org. The settings live in the repository's own git config (`.git/config`, shared by all its worktrees), never in tracked files.

`<scripts>` below is the `scripts/` directory beside this `SKILL.md`; use its absolute path.

## Is this repository set up?

```bash
git config --get gh-app-auth.login
```

Empty output: it isn't. Commit and open PRs as usual, and don't set it up unless the user asks.

## Working in a set-up repository

- **Commit** with the person who runs the agent as co-author. `user.name` and `user.email` already name the bot, and signing is off, because GitHub can't verify a bot commit signed with a personal key.

  ```bash
  git commit -m "<message>" --trailer "Co-authored-by: $(git config --get gh-app-auth.coauthor)"
  ```

- **Push** with plain `git push`. The repository's credential helper mints a fresh app token on every call.
- **Every `gh` command that writes** goes through `gh app-auth exec`, or it runs as the user:

  ```bash
  gh app-auth exec -- gh pr create --title "<title>" --body "<body>"
  ```

  The same goes for `gh pr edit`, `gh pr comment`, `gh pr merge`, `gh issue ...` and any `gh api` call that isn't a GET. Reads can run either way. Outside the repository, add `--repo <host>/<owner>/<repo>` before `--`.
- Never print, export or save a token (`GH_TOKEN=$(...)`). It expires within the hour; `exec` and the helper make a new one each time.

## Setting a repository up

When the user asks for it, run:

```bash
bash <scripts>/gh-app-identity.sh setup
```

It finds the app that gh-app-auth routes this repository to, asks GitHub for the bot's login and user ID, and sets in local git config: the bot as author (`<id>+<login>@users.noreply.github.com`), `commit.gpgsign false`, the current git identity as co-author, and a credential helper list holding gh-app-auth alone. Pass `--coauthor "Name <email>"` to credit someone else. Rerunning it is safe.

If it says no app works for the repository, the app isn't set up on this machine yet: follow `new-app.md`, beside this file.

If it warns that `origin` pushes over SSH, those pushes go out as the user. Ask before switching: `git remote set-url --push origin https://<host>/<owner>/<repo>.git`.

`bash <scripts>/gh-app-identity.sh off` reverses it.

## When auth fails

Only after a failure, not before every commit, run the check once. It mints a new token, so it also proves whether renewal works:

```bash
bash <scripts>/gh-app-identity.sh status
```

Exit 0 means it's fine: retry the failed command once. Exit 2 means the repository isn't set up. Exit 1 lists the problems:

| Problem or error | Fix |
|---|---|
| user.name, user.email, signing or helper list wrong | Rerun `setup`, then retry |
| `GIT_AUTHOR_*` or `GIT_COMMITTER_*` set in the environment | Unset them for the commit |
| `GH_TOKEN` exported, or `HTTP 401: Bad credentials` from plain `gh` | Run the command through `gh app-auth exec` |
| `could not mint a token`, with a JWT or private key error | Run `gh app-auth list --verify-keys`. Key not accessible: ask the user to unlock their keychain. Accessible: check the clock is right (`date -u`), since a JWT is only valid for minutes. Otherwise GitHub rejected the key: it was revoked, or belongs to another app. Reauthorize (below) |
| `404`, `installation` errors, or `Resource not accessible by integration` | The app isn't installed on this repository or lacks a permission: ask the user to fix it in the app's settings, then `gh app-auth scope --refresh` |
| `refusing to allow a GitHub App to create or update workflow` | The app needs the Workflows permission: ask the user |
| `unknown command "exec"` | `gh extension upgrade app-auth` |

**Reauthorizing** needs a new private key, which only the user can create: in the app's settings, "Generate a private key". Ask them for the downloaded file's path, never its contents, then run:

```bash
bash <scripts>/gh-app-identity.sh rekey <path-to-private-key.pem>
```

It stores the key in the OS keyring for the same app, patterns and priority, and tests it. Then tell the user the `.pem` file can be deleted; don't delete it yourself.

Don't retry a failing push or `gh` call more than once without running `status`, and never fall back to the user's own credentials to get past an app failure: ask the user instead.
