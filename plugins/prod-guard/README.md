# prod-guard

Runs one request against a production or otherwise sensitive cloud account, with a read-only guard that stays in force for the rest of the conversation.

## Install

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install prod-guard@ai-toolkit
```

Nothing else is needed. The plugin is a single skill that only you can invoke: Claude never loads it on its own.

## Usage

```text
/prod-guard:prod-guard <provider> <account|profile|project> <prompt...>
```

For example:

```text
/prod-guard:prod-guard aws prod-readonly which S3 buckets allow public reads?
/prod-guard:prod-guard gcp my-prod-project why did the checkout service restart overnight?
```

`/prod-guard` works too, unless another command already uses that name.

## What it does

1. Splits the arguments into the provider, the account and your request.
2. Prints a disclaimer naming the account: operations must be read-only or metadata inspections, and changes are never allowed, even if you ask. Claude confirms it understands before it starts.
3. Carries out your request with read-only operations only.
4. Keeps the guard for the rest of the conversation. Before each later operation on that account, Claude re-checks that it is read-only. When a change seems necessary, Claude stops and asks you to make it yourself, even if you tell it to go ahead.

## Limits

The guard is an instruction Claude follows, not a technical control. Use it alongside read-only credentials, such as an AWS role with `ReadOnlyAccess` or a GCP `roles/viewer` binding, and keep permission prompts on for cloud CLIs.

## Agent support

Claude Code only. Codex has no plugin equivalent: its custom prompts, which took arguments, are deprecated and can't be shipped in a plugin, and its skills don't substitute arguments.
