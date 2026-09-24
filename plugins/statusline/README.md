# statusline

A three-line statusline for Claude Code, drawn with Nerd Font icons in 24-bit colour. Catppuccin Macchiato in dark mode, Latte in light mode.

```text
 NORMAL  ·   my-app/src  ·   main  ·  +42 -7
 Opus 4.7  ·   ▃ high | 󱔏 Explanatory  ·   ◑ 42%  (84k/200k)
󱎫 2h 14m  ·   $1.23  23% session  ·  󱨲  41% weekly
```

| Line | Shows |
|---|---|
| 1 | Vim mode, when it's on. The git repo and your path inside it, the branch, and lines added and removed since `HEAD`, counting untracked files. Outside a repo, the working directory |
| 2 | Model, effort level, output style (unless it's the default), and context window usage |
| 3 | When the 5-hour limit resets, session cost, 5-hour (`session`) usage and 7-day (`weekly`) usage. With none of those to show, the session's running time |

Anything with no data is left out. Usage turns yellow at 60% and red at 85%.

## Requirements

- A [Nerd Font](https://www.nerdfonts.com) set as your terminal font. Without one, the icons show as boxes.
- A terminal with 24-bit colour, such as Ghostty, iTerm2, WezTerm, Kitty or Alacritty. Inside tmux, also enable it there: `set -as terminal-features ',*:RGB'`.
- `python3` 3.9 or later on `PATH`. The one that ships with macOS is fine.
- `git`, for line 1.

## Install

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install statusline@ai-toolkit
```

Then run `/statusline:setup` in Claude Code. A plugin can't set your `statusLine` itself, so this command does it once. The statusline appears straight away.

## What setup does

`/statusline:setup` runs `scripts/setup_statusline.py`, which sets this in `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json`):

```json
"statusLine": {
  "type": "command",
  "command": "python3 \"$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline.py\"",
  "padding": 0,
  "refreshInterval": 1
}
```

- Every other setting is kept, in order.
- If `settings.json` is a symlink, as with dotfiles managers, the file it points to is updated and the link stays.
- If you already have a different `statusLine`, it shows you both and asks before replacing yours. Extra keys you set on it, like `hideVimModeIndicator`, are kept.
- Running it again when everything's in place changes nothing.

The statusline shows the vim mode itself, so you may want to add `"hideVimModeIndicator": true` to the block to hide Claude Code's own `-- INSERT --`.

## Why the path never changes

Claude Code installs each plugin version in its own directory, so a path into the plugin would break on every update. Instead, `statusLine` runs a symlink in the plugin's persistent data directory, `${CLAUDE_PLUGIN_DATA}`, which Claude Code keeps across updates. A SessionStart hook, `scripts/link_statusline.sh`, points that link at the installed version's script at the start of every session. It prints nothing, does nothing when the link is already right, and never blocks a session.

## Theme

The first of these that gives an answer wins:

| Source | Notes |
|---|---|
| `CLAUDE_STATUSLINE_THEME` set to `dark` or `light` | Export it before starting Claude Code, or put it in front of the command: `CLAUDE_STATUSLINE_THEME=light python3 ...` |
| `~/.local/share/theme-monitor/theme-change.trigger` | Written by [theme-monitor](https://github.com/wmxscott/theme-monitor), if you run it |
| macOS appearance | `defaults read -g AppleInterfaceStyle` |
| Otherwise | Dark |

The statusline redraws every second, and without theme-monitor each redraw runs `defaults`. [theme-monitor](https://github.com/wmxscott/theme-monitor) is a small macOS service that updates the trigger file whenever the appearance changes, so the statusline only has to read a file:

```sh
brew install wmxscott/tap/theme-monitor
brew services start theme-monitor
```

If you later stop theme-monitor, delete the trigger file too. It keeps the last appearance it saw, which would otherwise win over the macOS check.

## Uninstall

1. Remove the `statusLine` block from `~/.claude/settings.json`, or run `/statusline` and ask Claude to remove it.
2. `claude plugin uninstall statusline@ai-toolkit`

Do step 1 first. Uninstalling deletes the plugin's data directory, and with it the file `statusLine` runs.

## Agent support

Claude Code only.
