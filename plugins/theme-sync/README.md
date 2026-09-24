# theme-sync

Switches Claude Code between its light and dark themes the moment the macOS appearance changes, in every open session.

## Why not `"theme": "auto"`?

Claude Code's built-in `auto` theme matches the terminal's background. In testing on Claude Code 2.1.282, in Ghostty with Herdr on macOS, it picked the theme when the session started but didn't switch mid-session: after macOS went light and the terminal followed, Claude kept its dark palette until the session was reloaded.

theme-sync switches immediately when the macOS appearance changes, without a reload.

If your terminal and Claude Code version do switch `auto` live, `"theme": "auto"` is all you need and you don't need this plugin.

## Requirements

- macOS. Anywhere else the plugin does nothing.
- [theme-monitor](https://github.com/wmxscott/theme-monitor), running. It's a small macOS service that writes `light` or `dark` to a trigger file the instant the appearance changes. theme-sync reads only that file and does no appearance detection of its own.

  ```sh
  brew install wmxscott/tap/theme-monitor
  brew services start theme-monitor
  ```

- `python3` 3.9 or later on `PATH`. The one that ships with macOS is fine.

## Install

Install and start theme-monitor first (see above), then:

```sh
claude plugin marketplace add wmxscott/ai-toolkit
claude plugin install theme-sync@ai-toolkit
```

Then run `/theme-sync:setup` in Claude Code. A plugin can't set your `theme` itself, so this command does it once.

## What setup does

`/theme-sync:setup` runs `scripts/setup_theme_sync.py`. It first checks that theme-monitor's trigger file is there. If it isn't, setup prints the install command above and changes nothing. Otherwise it:

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

- **Where the theme comes from.** theme-monitor's trigger file, `~/.local/share/theme-monitor/theme-change.trigger`. For testing, `CLAUDE_THEME_SYNC_THEME=dark` or `light` overrides it: that session syncs once and starts no watcher.
- **SessionStart hook.** `scripts/session_start.sh` syncs the theme file once, then starts a background watcher unless one is already running. It prints nothing, returns in well under a second, and never blocks a session. It does nothing until setup has created the theme file, or while the trigger file is missing.
- **Watcher.** One per user, whatever the number of sessions. It sleeps in the kernel (kqueue) until something it watches changes, and never polls:
  - a write to the trigger file rewrites the theme file within a few milliseconds. If the trigger file is deleted, recreated or replaced, the watcher picks up the new file;
  - the theme file is rewritten only when the theme changes, atomically, and through any symlink.
- **Lifetime.** Each session registers its Claude Code process, with its start time so a reused process ID doesn't count. The watcher is woken when a registered process exits, and exits itself once none is left. It also exits if you delete the theme file, uninstall the plugin or remove theme-monitor's folder. The next session starts a new one.
- **One at a time.** The watcher holds an exclusive lock on `watcher.pid` in the plugin's data directory, `~/.claude/plugins/data/theme-sync-ai-toolkit/`, for as long as it runs. The lock goes with the process, so a crash never leaves a stale pidfile behind.

### Customising the theme

Only `base` is managed. Add a `name` or `overrides` to `theme-sync.json` and they're kept. [Create a custom theme](https://code.claude.com/docs/en/terminal-config#create-a-custom-theme) lists the colour tokens. Overrides apply in both light and dark mode.

Editors that save by moving the old file aside are fine: the watcher only stops if the file stays missing for 2 seconds.

## Uninstall

1. Pick another theme with `/theme`, or remove `"theme": "custom:theme-sync"` from `~/.claude/settings.json`.
2. Delete `~/.claude/themes/theme-sync.json`. The watcher exits within a few seconds.
3. `claude plugin uninstall theme-sync@ai-toolkit`

## Agent support

Claude Code only.
