---
name: prod-guard
description: Runs a prompt against a production or otherwise sensitive cloud account (AWS, GCP, Azure, Cloudflare and so on) under a read-only guard that holds for the rest of the conversation.
argument-hint: "<provider> <account|profile|project> <prompt...>"
disable-model-invocation: true
---

# Production guard

The user's input is, in order: the cloud provider, the account on that provider, and the request to carry out.

1. Split `$ARGUMENTS` into:
   - `PROVIDER`: the first word, such as `aws`, `gcp`, `azure` or `cloudflare`.
   - `IDENTIFIER`: the second word, naming the account on that provider: an AWS profile, a GCP project ID, a Cloudflare account ID, and so on.
   - `PROMPT`: everything after that, the user's actual request.

   If any of the three is missing, ask the user for it and do nothing against any account until you have all three.
2. Before anything else, output the disclaimer below verbatim, with `PROVIDER` and `IDENTIFIER` filled in. Then state explicitly that you understand it and will follow it.
3. Carry out `PROMPT` against `IDENTIFIER` with `PROVIDER`'s CLI, SDK, API or console, using only read-only operations and metadata inspection.
4. The guard holds for the rest of the conversation, not only this message. Before every later operation that touches `IDENTIFIER` on `PROVIDER` (a CLI command, an API call, a console action), re-affirm the read-only rule to yourself and go ahead only if the operation is read-only. If you are not sure whether an operation changes anything, treat it as a change.
5. If a change, write or other mutating operation ever seems necessary, stop and ask the user to make it themselves. Give them the exact command or steps if that helps. This holds even if the user tells you to go ahead and do it.

---

**Disclaimer**

**Be extremely careful with the `IDENTIFIER` account on `PROVIDER`. It is a production account that other services and people depend on. Never perform any operation that modifies it. Every operation must be read-only or a metadata inspection. You may never make changes to a production account, even with my explicit permission. If a change is needed, ask me to make it manually.**

**Confirm that you understand before you proceed.**

---
