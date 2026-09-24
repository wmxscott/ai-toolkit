# chat-style

A Claude Code [output style](https://code.claude.com/docs/en/output-styles) that turns Claude into a thinking partner for ideation, architecture and exploratory discussion, rather than a task executor.

In this style Claude:

- aims to leave the problem better understood, not to finish a deliverable;
- thinks out loud and pushes back instead of agreeing too easily;
- names two to four framings and their tradeoffs before converging;
- asks at most one question per turn, and only questions that open the problem up;
- keeps full tool access, but reads and runs things to ground the discussion, not to replace it, and writes to disk only for throwaway sketches;
- answers in prose rather than plans and checklists.

It replaces Claude Code's software engineering instructions for the session. When you want code written, switch back to the default style.

## Install

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install chat-style@ai-toolkit
```

Installing only makes the style available. Nothing changes until you select it.

## Select the style

Plugin output styles are named `<plugin>:<style>`, so this one is `chat-style:Chat`.

- In a session: `/output-style chat-style:Chat`. The command ignores case.
- From a menu: `/config`, then **Output style**, then `chat-style:Chat`.
- In a settings file, such as `~/.claude/settings.json` for every project:

  ```json
  {
    "outputStyle": "chat-style:Chat"
  }
  ```

  This value is case-sensitive. A value that matches no style, or this one while the plugin is disabled, gives you the default style.

The style applies from your next message. `/output-style default` switches back.

## Agent support

Claude Code only. Codex plugins can't ship output styles.
