# Pi extensions

Extensions and themes for [Pi](https://github.com/earendil-works/pi). They load from the ai-toolkit Pi package, together with the skills of the plugins that support Pi:

```sh
pi install git:github.com/wmxscott/ai-toolkit
```

To load only these, without the skills, set the package's entry in `~/.pi/agent/settings.json` to:

```json
{
  "source": "git:github.com/wmxscott/ai-toolkit",
  "skills": []
}
```

The main README's [Choosing what loads](../README.md#choosing-what-loads) has the other filters. Each extension works without the others, so you can drop any of them. theme-switcher needs the themes.

If you already have copies of these files in `~/.pi/agent/extensions` or `~/.pi/agent/themes`, remove them: Pi would load both, and reports the duplicate theme names as collisions.

## `statusline.ts`

Replaces Pi's footer with three lines:

```text
 my-app/src  ·   main  ·  +42  ·  -7
 claude-opus  ·   ▃ high  ·   ○ 42%  (84k/200k)
󱎫 120k↑ 8k↓  ·   $1.23  ·  󱨲 session
```

| Line | Shows |
|---|---|
| 1 | The git repo and your path inside it, the branch, and lines added and removed since `HEAD`, counting untracked files. Outside a repo, the working directory |
| 2 | Model, thinking level (unless it's off) and context window usage, which turns yellow at 60% and red at 85% |
| 3 | Input and output tokens and cost for the current session branch |

Colours are Catppuccin Latte when [theme-monitor](https://github.com/wmxscott/theme-monitor) reports light mode, and Frappé otherwise. `/statusline` puts the footer back if another extension replaced it.

Needs a [Nerd Font](https://www.nerdfonts.com), a terminal with 24-bit colour, and `git` for line 1.

## `theme-switcher.ts`

Switches Pi to `catppuccin-latte` in light mode and `catppuccin-macchiato` in dark mode the moment the macOS appearance changes, in every open session. Both themes ship in this package.

It needs [theme-monitor](https://github.com/wmxscott/theme-monitor), a small macOS service that writes `light` or `dark` to `~/.local/share/theme-monitor/theme-change.trigger` whenever the appearance changes:

```sh
brew install wmxscott/tap/theme-monitor
brew services start theme-monitor
```

- It reads the trigger file when a session starts, then watches it and checks it again every second.
- It saves each switch to Pi's `theme` setting, as `/settings` would, so it takes over from any theme you picked there.
- Without the trigger file it uses the dark theme.

Pi's `light/dark` theme setting follows the terminal's appearance reports instead. If your terminal sends them, that may be all you need.

## `display.ts`

Draws each fenced code block in an assistant reply inside a frame, with its language in the top rule:

```text
── ts ──────────────────────────────
const answer = 42;
────────────────────────────────────
```

Pi's own Markdown renderer still does the syntax highlighting. The frame uses the theme's `accent` and `borderMuted` colours, and only appears in the terminal UI.

Adapted from the code-block renderer of [pix-display](https://github.com/xynogen/pix-mono/tree/main/packages/pix-display) by xynogen, under the MIT License. The copyright and licence notice is at the top of `display.ts`.

## `pr-tracker.ts`

Pi's half of the [pr-tracker plugin](../plugins/pr-tracker): it does in Pi what the plugin's hooks do in Claude Code and Codex, through the [pr-tracker](https://github.com/wmxscott/pr-tracker) CLI.

| Pi event | Runs | Does |
|---|---|---|
| `tool_result`, every tool | `pr-tracker hook --agent pi` | Records a PR a `bash` call created, even one that failed, then appends queued check and review changes to the tool's output, where the model reads them |
| `before_agent_start` | `pr-tracker hook --agent pi` | Delivers queued changes along with your prompt |
| `agent_before_settle` | `pr-tracker hook stop --agent pi` | When failing checks or a review decision are queued, hands them to the agent so the run keeps going, once per run. Otherwise shows you the queued changes as a notification, leaving them queued |
| `agent_settled` | `pr-tracker hook stop --agent pi`, every 30 seconds | In the terminal UI and RPC mode, after a run that wasn't aborted or failed: waits up to 59 minutes for failing checks or a review decision, then wakes the idle session with them. The next run stops it |

The tool events carry Pi's tool name, and the CLI decides from it: it records from `bash`, and from any tool whose name ends in `create_pull_request`, as an extension's GitHub MCP tool might. Everything the extension hands the model shows in the transcript as a `pr-tracker` message.

Set `notify.wake = false` in pr-tracker's settings to turn off continuing and waking.

It needs pr-tracker 1.1.0 or later, 1.2.0 for delivery on every tool and prompt, and 1.2.1 for continuing and waking. Older versions only show the changes as a notification at the end of a run. The [plugin's README](../plugins/pr-tracker/README.md) covers installing it. It looks for `pr-tracker` on `PATH`, then in `/opt/homebrew/bin`, `/usr/local/bin`, `/home/linuxbrew/.linuxbrew/bin` and `~/.local/bin`, once per session. Without it, the extension does nothing. It never fails a tool call: a missing, slow (10 seconds) or broken CLI leaves the result as it was.

Pi has no MCP support of its own, so most PRs it records come from `bash`. `pr-tracker adopt` attaches any other.

## Themes

`themes/catppuccin-latte.json` and `themes/catppuccin-macchiato.json` are [Catppuccin](https://catppuccin.com) Latte and Macchiato for Pi. Pick them in `/settings`, or let theme-switcher do it.
