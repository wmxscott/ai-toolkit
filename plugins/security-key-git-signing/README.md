# security-key-git-signing

Stops the agent from running a signed git operation while your GPG signing key's hardware security key (a YubiKey or other OpenPGP smart card) is unplugged.

Without it, the agent runs `git commit`, gpg can't reach the card, and git fails with `gpg failed to sign the data`, sometimes halfway through a rebase or merge. The `security-key-git-signing` skill checks first and asks you to insert the key.

## Install

Claude Code:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install security-key-git-signing@ai-toolkit
```

Codex:

```sh
codex plugin marketplace add wmxscott/ai-toolkit
codex plugin add security-key-git-signing@ai-toolkit
```

Needs `git` and GnuPG. The plugin is a single skill, with no hooks or scripts. The agent loads it by itself before commits and tags.

## What it checks

Before any git operation that may sign, in order:

| Check | Command | Then |
|---|---|---|
| Will git sign? | `git config --bool --get commit.gpgsign` (or `tag.gpgsign`), or `-S`/`-s`/`-u` given | No: run it |
| Is it GPG? | `git config --get gpg.format` | `ssh` or `x509`: run it |
| Is the key on a card? | `sec>` or `ssb>` in `gpg --list-secret-keys` | No: run it |
| Is the card plugged in? | `gpg --card-status` | Yes: run it. No: ask you to insert it, wait, check again |

It never retries in a loop and never turns signing off to get past a missing key.

## PIN and touch prompts

Agents run git without a terminal, so gpg-agent can't ask for the card's PIN with a terminal pinentry such as `pinentry-curses`. Set a graphical `pinentry-program` in `~/.gnupg/gpg-agent.conf`: `pinentry-mac` on macOS, `pinentry-gnome3` or `pinentry-qt` on Linux.

On macOS, [seckey-dialog](https://github.com/wmxscott/seckey-dialog) is an optional companion: one native dialog program for gpg-agent's PIN prompts and ssh's security-key touch and PIN prompts.

## Agent support

| Agent | Manifest |
|---|---|
| Claude Code | `.claude-plugin/plugin.json` |
| Codex | `plugin.json` ([Agent Plugins](https://agent-plugins.org) format) |

Both load the same `skills/` directory.
