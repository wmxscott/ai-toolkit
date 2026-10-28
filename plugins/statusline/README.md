# statusline

A three-line statusline for Claude Code, drawn with Nerd Font icons in 24-bit colour. Catppuccin Macchiato in dark mode, Latte in light mode. It's a small Go program: each redraw starts one process, and every session in a worktree shares one set of git line counts.

```text
 NORMAL  ·   my-app/src  ·   main  ·  +42 -7
 Opus 4.7  ·   ▃ high | 󱔏 Explanatory  ·   ◑ 42%  (84k/200k)
󱎫 2h 14m  ·   $1.23  23% session  ·  󱨲  41% weekly
```

| Line | Shows |
|---|---|
| 1 | Vim mode, when it's on. The git repo and your path inside it, the branch, and lines added and removed since `HEAD`, counting untracked files. Outside a repo, the working directory |
| 2 | Model, effort level, output style (unless it's the default), and context window usage |
| 3 | When the 5-hour limit resets, session cost, 5-hour (`session`) usage and 7-day (`weekly`) usage. With none of those to show, the session's running time |

Anything with no data is left out. Usage turns yellow at 60% and red at 85%.

## Requirements

- macOS or Linux, on arm64 or x86-64.
- A [Nerd Font](https://www.nerdfonts.com) set as your terminal font. Without one, the icons show as boxes.
- A terminal with 24-bit colour, such as Ghostty, iTerm2, WezTerm, Kitty or Alacritty. Inside tmux, also enable it there: `set -as terminal-features ',*:RGB'`.
- `curl`, and `shasum` or `sha256sum`, to download the binary.
- `git`, for line 1.
- `python3` 3.9 or later, for `/statusline:setup` only. The one that ships with macOS is fine. The statusline itself doesn't use Python.

## Install

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install statusline@ai-toolkit
```

Then run `/statusline:setup` in Claude Code. A plugin can't set your `statusLine` itself, so this command does it once.

## How the binary arrives

The plugin doesn't ship the binary. At the start of each session, a SessionStart hook, `scripts/link_statusline.sh`, looks for the installed version's binary in the plugin's data directory. If it's missing, the hook downloads it in the background from the GitHub release `statusline-v<version>` and checks its SHA-256 against `checksums.txt` in the plugin, discarding it on a mismatch. Setup runs the same download and waits for it.

Until the first download completes, the statusline is blank: for example, after a first install while offline. Each new session retries. After a plugin update, the previous binary keeps working until the new one lands.

## What setup does

`/statusline:setup` runs `scripts/setup_statusline.py`, which downloads the binary and sets this in `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json`):

```json
"statusLine": {
  "type": "command",
  "command": "\"$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline\"",
  "padding": 0,
  "refreshInterval": 15
}
```

- Every other setting is kept, in order.
- If `settings.json` is a symlink, as with dotfiles managers, the file it points to is updated and the link stays.
- If you already have a different `statusLine`, it shows you both and asks before replacing yours. Extra keys you set on it, like `hideVimModeIndicator`, are kept.
- Running it again when everything's in place changes nothing.

Claude Code redraws the statusline on its own events, such as each new message, `/compact` or a mode change. `refreshInterval: 15` adds a redraw every 15 seconds as a backstop, so git counts and reset times stay current while a session sits idle.

The statusline shows the vim mode itself, so you may want to add `"hideVimModeIndicator": true` to the block to hide Claude Code's own `-- INSERT --`.

## Why the path never changes

Claude Code installs each plugin version in its own directory, so a path into the plugin would break on every update. Instead, `statusLine` runs a symlink in the plugin's persistent data directory, `${CLAUDE_PLUGIN_DATA}`, which Claude Code keeps across updates. The SessionStart hook points that link at the installed version's binary. Apart from the upgrade notice below, it prints nothing, does nothing when the link is already right, and never blocks a session.

## Cache

The statusline keeps small files in `~/Library/Caches/ai-toolkit-statusline/` on macOS, and in `$XDG_CACHE_HOME/ai-toolkit-statusline/` (or `~/.cache/ai-toolkit-statusline/`) on Linux: each worktree's line counts, shared by every session in it, and the last macOS appearance it read. Line counts refresh when `HEAD` or the index changes, or after 5 seconds. The directory is safe to delete at any time.

## Theme

The first of these that gives an answer wins:

| Source | Notes |
|---|---|
| `CLAUDE_STATUSLINE_THEME` set to `dark` or `light` | Export it before starting Claude Code, or put it in front of the command: `CLAUDE_STATUSLINE_THEME=light "$HOME/..."` |
| `~/.local/share/theme-monitor/theme-change.trigger` | Written by [theme-monitor](https://github.com/wmxscott/theme-monitor), if you run it |
| macOS appearance | `defaults read -g AppleInterfaceStyle`, at most once every 5 seconds |
| Otherwise | Dark |

Without theme-monitor, the statusline runs `defaults` now and then, and can take up to 5 seconds to notice an appearance change. [theme-monitor](https://github.com/wmxscott/theme-monitor) is a small macOS service that updates the trigger file whenever the appearance changes, so the statusline only reads a file and picks up a change at the next redraw:

```sh
brew install wmxscott/tap/theme-monitor
brew services start theme-monitor
```

If you later stop theme-monitor, delete the trigger file too. It keeps the last appearance it saw, which would otherwise win over the macOS check.

## Upgrading from 1.x

Version 1 ran a Python script. After the update, each session starts with the notice "statusline: run /statusline:setup to switch to the faster version". Run `/statusline:setup`: it replaces the old `python3 ".../statusline.py"` block without asking, keeps any extra keys you added to it, and removes the old script's link.

## Uninstall

1. Remove the `statusLine` block from `~/.claude/settings.json`, or run `/statusline` and ask Claude to remove it.
2. `claude plugin uninstall statusline@ai-toolkit`
3. Optionally, delete the cache directory (see "Cache").

Do step 1 first. Uninstalling deletes the plugin's data directory, and with it the binary `statusLine` runs.

## Agent support

Claude Code only.
