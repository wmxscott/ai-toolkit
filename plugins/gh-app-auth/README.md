# gh-app-auth

Lets an AI agent commit, push and open pull requests as a GitHub App's bot (`<app>[bot]`) instead of as you, one app per GitHub account or org, through the [gh-app-auth](https://github.com/AmadeusITGroup/gh-app-auth) `gh` extension. You stay on every commit as co-author.

It works per repository, and only for the agent. In a repository you set up, the agent:

- commits and pushes through `git app`, a git alias that makes `<app>[bot] <id+app[bot]@users.noreply.github.com>` the author, adds a `Co-authored-by:` trailer naming you, and logs in with a fresh app token on every push;
- runs `gh pr create` and other writing `gh` commands through `gh app-auth exec`, so the PR is the app's;
- checks the setup and mints a new token when auth fails, and stores a new private key when the app needs reauthorizing.

Your own `git commit`, `git push` and `gh` commands are untouched: same name, same signing key, same login. Other repositories are untouched too.

## Install

Claude Code:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install gh-app-auth@ai-toolkit
```

Codex:

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add gh-app-auth@ai-toolkit
```

Pi:

```sh
pi install git:github.com/wmxscott/ai-toolkit
```

OpenCode: add the repository to `opencode.json` and restart OpenCode. The key is `plugin` in OpenCode 1 and `plugins` in OpenCode 2.

```json
{
  "plugin": ["ai-toolkit@git+https://github.com/wmxscott/ai-toolkit.git"]
}
```

The Pi package and the OpenCode plugin bring in every ai-toolkit plugin that supports that agent, which are those ticked in the [main README](../../README.md#plugins).

## Requirements

- `git` 2.32 or later, `bash`, and [`gh`](https://cli.github.com/) with the extension: `gh extension install AmadeusITGroup/gh-app-auth`.
- `jq`, only to store a new private key (`rekey`).
- A GitHub App per account or org, installed there, with Contents and Pull requests set to Read and write. [`new-app.md`](skills/gh-app-auth/new-app.md) walks through creating one.

## Use

Once the app is set up with `gh app-auth setup`, ask the agent to set up a repository to act as the app, or run it yourself:

```sh
bash skills/gh-app-auth/scripts/gh-app-identity.sh setup     # add git app here
bash skills/gh-app-auth/scripts/gh-app-identity.sh status    # check, and mint a fresh token
bash skills/gh-app-auth/scripts/gh-app-identity.sh rekey ~/Downloads/app.private-key.pem
bash skills/gh-app-auth/scripts/gh-app-identity.sh off       # remove git app
```

`setup` adds only these to the repository's `.git/config`:

| Setting | Value |
|---|---|
| `alias.app` | The `git app` alias |
| `gh-app-auth.login`, `gh-app-auth.userid` | The bot's login and user ID, looked up through the app |
| `gh-app-auth.coauthor` | Your git identity at setup time, or `--coauthor "Name <email>"` |
| `gh-app-auth.repo` | `<host>/<owner>/<repo>`, from `origin` |

Nothing else changes, so plain `git` behaves as before. `git app <command>` runs `git <command>` with these options for that one command:

| Option | Why |
|---|---|
| `user.name`, `user.email` | The bot as author and committer |
| `commit.gpgsign=false` | GitHub can't verify a bot's commit signed with your personal key: it would show as Unverified. Bot commits show no badge instead, and a branch rule that requires signed commits will reject them |
| `--trailer "Co-authored-by: ..."`, on `commit` only | Credits you; `trailer.ifexists=addIfDifferent` keeps it to one |
| An empty `credential.https://<host>/<owner>.helper`, then `!gh app-auth git-credential` | Clears the helpers your system and global config add, such as the macOS Keychain or `credential.helper store`, so git can't push as you or replay an expired app token |
| `url.https://<host>/.insteadOf` for `git@<host>:` and `ssh://git@<host>/` | SSH would bypass the app. `insteadOf` rewrites a `pushurl` too; `pushInsteadOf` doesn't |

Run `git config alias.app` to read the alias itself.

## Sharing an app

One app can serve a whole team. Each person or machine should generate its own private key for it (an app can have several), so one can be revoked without breaking the others.
