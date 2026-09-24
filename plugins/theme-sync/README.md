# theme-sync

Switches Claude Code between its light and dark themes the moment the macOS appearance changes, in every open session.

## Why not `"theme": "auto"`?

Claude Code's built-in `auto` theme matches the terminal's background. In testing on Claude Code 2.1.282, in Ghostty with Herdr on macOS, it picked the theme when the session started but didn't switch mid-session: after macOS went light and the terminal followed, Claude kept its dark palette until the session was reloaded.

theme-sync switches immediately when the macOS appearance changes, without a reload.

If your terminal and Claude Code version do switch `auto` live, `"theme": "auto"` is all you need and you don't need this plugin.

## Requirements

- macOS. Elsewhere the theme stays dark unless [theme-monitor](#theme-monitor)'s trigger file or `CLAUDE_THEME_SYNC_THEME` says otherwise.
- `python3` 3.9 or later on `PATH`. The one that ships with macOS is fine.

## Install

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install theme-sync@ai-toolkit
```

Then run `/theme-sync:setup` in Claude Code. A plugin can't set your `theme` itself, so this command does it once.

## What setup does

`/theme-sync:setup` runs `scripts/setup_theme_sync.py`, which:

1. writes the theme file `~/.claude/themes/theme-sync.json` for the current appearance;
2. sets this in `~/.claude/settings.json`:

   ```json
   "theme": "custom:theme-sync"
   ```

3. starts the watcher.

With `CLAUDE_CONFIG_DIR` set, both files live there instead of `~/.claude`.

- Every other setting is kept, in order.
- If `settings.json` is a symlink, as with dotfiles managers, the file it points to is updated and the link stays.
- If you already have a different `theme`, it shows you both and asks before replacing yours.
- Running it again when everything's in place changes nothing.

Claude Code only watches `~/.claude/themes/` if the folder existed when it started. If setup had to create it, restart Claude Code once. Setup tells you when.

## How it works

The theme file holds a `base` of `dark` or `light`. Claude Code reloads custom theme files when they change, so rewriting `base` switches the theme in every open session.

- **SessionStart hook.** `scripts/session_start.sh` syncs the theme file once, then starts a background watcher unless one is already running. It prints nothing, returns in well under a second, and never blocks a session. Until setup has created the theme file, it does nothing.
- **Watcher.** One per user, whatever the number of sessions. It checks the appearance about once a second and rewrites the file only when the theme changes, atomically, through any symlink. Between checks it sleeps.
- **Lifetime.** Each session registers its Claude Code process. The watcher exits once none of them is left running. It also exits if you delete the theme file or uninstall the plugin. The next session starts a new one.
- **One at a time.** The watcher holds an exclusive lock on `watcher.pid` in the plugin's data directory, `~/.claude/plugins/data/theme-sync-ai-toolkit/`, for as long as it runs. The lock goes with the process, so a crash never leaves a stale pidfile behind.

### Where the theme comes from

The first of these that gives an answer wins:

| Source | Notes |
|---|---|
| `CLAUDE_THEME_SYNC_THEME` set to `dark` or `light` | For testing. That session syncs once and starts no watcher |
| `~/.local/share/theme-monitor/theme-change.trigger` | Written by [theme-monitor](#theme-monitor), if you run it |
| macOS appearance | `defaults read -g AppleInterfaceStyle`, every 2 seconds |
| Otherwise | Dark |

### Customising the theme

Only `base` is managed. Add a `name` or `overrides` to `theme-sync.json` and they're kept. [Create a custom theme](https://code.claude.com/docs/en/terminal-config#create-a-custom-theme) lists the colour tokens. Overrides apply in both light and dark mode.

## theme-monitor

Without it, the watcher runs `defaults` every 2 seconds to read the appearance, so a switch can take up to 2 seconds to show.

[theme-monitor](https://github.com/wmxscott/theme-monitor) is a small macOS service that writes `light` or `dark` to a trigger file the instant the appearance changes. With it running, the watcher reads that file instead: it switches within about a second, and never runs `defaults`.

```sh
brew install wmxscott/tap/theme-monitor
brew services start theme-monitor
```

If you later stop theme-monitor, delete the trigger file too. It keeps the last appearance it saw, which would otherwise win over the macOS check.

## Uninstall

1. Pick another theme with `/theme`, or remove `"theme": "custom:theme-sync"` from `~/.claude/settings.json`.
2. Delete `~/.claude/themes/theme-sync.json`. The watcher exits within a few seconds.
3. `claude plugin uninstall theme-sync@ai-toolkit`

## Agent support

Claude Code only.
