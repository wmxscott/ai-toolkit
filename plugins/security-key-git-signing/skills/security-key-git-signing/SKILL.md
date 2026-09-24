---
name: security-key-git-signing
description: Use when about to run git commit, git tag -s, or any other GPG-signed git operation where commit.gpgsign or tag.gpgsign may be enabled and the signing key may be on a hardware security key (YubiKey, OpenPGP smart card). Checks the key is plugged in first, so signing doesn't fail halfway.
---

# Security key git signing

When the GPG signing key lives on a hardware security key and the key isn't plugged in, git fails with an unhelpful `gpg failed to sign the data`. Before any git operation that signs, check whether signing needs a hardware key and whether it is present. If it isn't, ask the user to insert it before running the command.

## When to use

Before any git operation that may sign:

- `git commit`, including `--amend`, and anything else that creates commits: `merge`, `rebase`, `cherry-pick`, `revert`, `am`
- `git tag -s` or `git tag -u <key>`
- any operation given `-S` or `--gpg-sign`

## Procedure

Run the checks in order. As soon as one says signing doesn't need a hardware key, stop checking and run the git command.

### 1. Will git sign?

```bash
git config --bool --get commit.gpgsign
```

```bash
git config --bool --get tag.gpgsign
```

A commit signs when `commit.gpgsign` prints `true` or the command has `-S`. A tag signs when `tag.gpgsign` prints `true` or the command has `-s` or `-u`. No output means the setting is off. If the operation won't sign, skip the remaining checks.

### 2. Does git sign with GPG?

```bash
git config --get gpg.format
```

No output or `openpgp` means GPG: carry on. `ssh` or `x509` means git signs with another tool, so these checks don't apply.

### 3. Is the signing key on a hardware key?

GPG marks key material held on a card with `>` after `sec` or `ssb` in its key listing, for example `ssb>`.

```bash
gpg --list-secret-keys $(git config --get user.signingkey) 2>/dev/null | grep -qE '^(sec|ssb)>'
```

The substitution is left unquoted on purpose: when `user.signingkey` is unset, gpg lists every secret key.

- Exit 0: the key is on a card. Go to step 4.
- Exit 1: the key is in software. Run the git command.

### 4. Is the hardware key plugged in?

```bash
gpg --card-status >/dev/null 2>&1
```

- Exit 0: a card is present. Run the git command.
- Anything else: no card. Go to step 5.

### 5. Ask for the key

Don't run the git command. Tell the user:

```text
Your security key isn't plugged in. Insert it, then tell me to continue.
```

Wait for them to confirm, run step 4 again, then run the git command.

### 6. PIN and touch

Signing may need the card's PIN, and a touch if the key has a touch policy. gpg-agent asks for the PIN through its `pinentry-program`. Agents run git without a terminal, so a terminal pinentry such as `pinentry-curses` can't prompt and signing fails. A graphical pinentry works: `pinentry-mac` on macOS, `pinentry-gnome3` or `pinentry-qt` on Linux. On macOS, [seckey-dialog](https://github.com/wmxscott/seckey-dialog) is another option: native PIN dialogs for gpg-agent that also cover ssh's security-key prompts.

When signing starts, tell the user to enter the PIN or touch the key if asked.

## Quick reference

| Condition | Action |
|---|---|
| The operation doesn't sign | Run it |
| `gpg.format` is `ssh` or `x509` | Run it: not GPG |
| No `sec>` or `ssb>` in the key listing | Run it: software key |
| `gpg --card-status` exits 0 | Run it: key present |
| `gpg --card-status` fails | Ask the user to insert the key, wait, check again |

## Common mistakes

- **Running the command first and checking on failure.** GPG's errors are cryptic and a failed rebase or merge leaves work half done. Check before, not after.
- **Checking only `user.signingkey`.** The key ID doesn't say where the key lives. Only the `>` marker in the key listing does.
- **Retrying in a loop.** Ask once and wait. The user may need to find the key, enter a PIN or touch it.
- **Turning signing off to get past the check.** Never add `--no-gpg-sign` or change `commit.gpgsign` to work around a missing key. Ask the user.
