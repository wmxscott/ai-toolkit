# Adding a GitHub App for an account or org

One app per GitHub account or org. The user creates it in the browser; the agent can run the commands once they have the key file.

## 1. The user creates the app

In the account's or org's settings: Developer settings, GitHub Apps, New GitHub App.

- **Webhook:** untick "Active".
- **Repository permissions:** Contents and Pull requests: Read and write. Add Issues to work on issues, and Workflows to change files under `.github/workflows/`.
- **Where can this GitHub App be installed:** Only on this account.

Then, on the app's page:

1. Note the **Client ID**.
2. **Generate a private key**. It downloads a `.pem` file.
3. **Install App** on the account or org, for all repositories or the ones the agent works in.

Several people or machines can share one app, but each should generate its own private key, so one can be revoked without breaking the others. Never pass a key file around.

## 2. Store the key and test it

```bash
gh extension install AmadeusITGroup/gh-app-auth   # or: gh extension upgrade app-auth
GH_APP_PRIVATE_KEY="$(cat <path-to-key.pem>)" gh app-auth setup \
  --client-id <client-id> --patterns "github.com/<owner>/*"
gh app-auth test --repo github.com/<owner>/<repo>
```

`setup` stores the key in the OS keyring (Keychain, Credential Manager or Secret Service) and finds the installation ID itself. The variable is set for that one command only. The user can then delete the `.pem` file.

Don't run `gh app-auth gitconfig --sync --global`: it would make the user's own pushes in that org go out as the app too. `gh-app-identity.sh setup` sets up each repository on its own.

## 3. Set up the repository

Back to "Setting a repository up" in `SKILL.md`.
