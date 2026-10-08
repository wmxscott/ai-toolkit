# plain-talk

Makes Claude Code reply in short, plain language you can skim while it works, and points out what needs you.

- **Reply rules.** Adds a section to the system prompt: a one-line TLDR first, short chunks, everyday words, acronyms and jargon explained the first time, and a `Next:` line at the end. It works under any output style.
- **Needs you header.** When a reply needs your decision, approval or action, Claude writes a `**Needs you**` header. The plugin draws it in pink with a Nerd Font flag icon. In the terminal, pink is your terminal theme's bright magenta, so it follows your colour scheme. Other replies are left alone.
- **`/overview`.** Recaps the session: goal, done, in progress, not started, what needs you, and the next step.

The flag icon needs a [Nerd Font](https://www.nerdfonts.com) in your terminal. Without one, the header still shows in pink.

## Install

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install plain-talk@ai-toolkit
```

## Tests

```sh
claude plugin test plugins/plain-talk
```
