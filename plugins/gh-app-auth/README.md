# gh-app-auth

Lets an AI agent commit, push and open pull requests as a GitHub App's bot (`<app>[bot]`) instead of as you, one app per GitHub account or org, through the [gh-app-auth](https://github.com/AmadeusITGroup/gh-app-auth) `gh` extension. You stay on every commit as co-author.

It works per repository. In a repository you set up, the agent:

- commits as `<app>[bot] <id+app[bot]@users.noreply.github.com>`, with a `Co-authored-by:` trailer naming you;
- pushes with a fresh app token on every push;
- runs `gh pr create` and other writing `gh` commands through `gh app-auth exec`, so the PR is the app's;
- checks the setup and mints a new token when auth fails, and stores a new private key when the app needs reauthorizing.

Other repositories are untouched.

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
bash skills/gh-app-auth/scripts/gh-app-identity.sh setup     # act as the app here
bash skills/gh-app-auth/scripts/gh-app-identity.sh status    # check, and mint a fresh token
bash skills/gh-app-auth/scripts/gh-app-identity.sh rekey ~/Downloads/app.private-key.pem
bash skills/gh-app-auth/scripts/gh-app-identity.sh off       # back to your own identity
```

`setup` writes only to the repository's `.git/config`:

| Setting | Value |
|---|---|
| `user.name`, `user.email` | The bot's login, and `<id>+<login>@users.noreply.github.com` |
| `commit.gpgsign` | `false` |
| `credential.https://<host>/<owner>.helper` | An empty value, then `!gh app-auth git-credential` |
| `credential.https://<host>.useHttpPath` | `true` |
| `gh-app-auth.login`, `.userid`, `.coauthor`, `.repo` | What the agent reads |

The co-author is your git identity at setup time; pass `--coauthor "Name <email>"` to choose another.

Signing is off because GitHub can't verify a bot's commit signed with your personal key: it would show as Unverified. Bot commits show no badge instead. A branch rule that requires signed commits will reject them.

The empty helper value clears the helpers your system and global git config add, such as the macOS Keychain or `credential.helper store`. Without it, git tries those first: it may push as you, or save the app's one-hour token and send it back after it has expired.

Pushes over SSH bypass the app and go out as you. `setup` and `status` warn when `origin` pushes over SSH, and print the command that switches it to HTTPS.

## Sharing an app

One app can serve a whole team. Each person or machine should generate its own private key for it (an app can have several), so one can be revoked without breaking the others.
