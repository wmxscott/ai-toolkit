---
name: setup
description: Sets Claude Code's theme to the theme-sync theme, which follows the macOS light/dark appearance. Run once after installing the plugin.
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_theme_sync.py *)
---

Point the user's `theme` setting at the theme-sync theme. The bundled script does all the work: it writes the theme file, edits `settings.json` safely and starts the watcher. Never edit `settings.json` or the theme file yourself.

1. Run:

   ```sh
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_theme_sync.py "${CLAUDE_PLUGIN_DATA}"
   ```

2. Act on its exit status:
   - **0**: done, or already set up. Show the user the script's output. If it says to restart Claude Code, tell them that too.
   - **3**: the user already has a different `theme`. Nothing has changed yet. Show them the current and proposed values from the output and ask whether to replace the current one. Only if they say yes, run the same command again with `--force` added. If they say no, stop and change nothing.
   - **Anything else**: show the error. Don't try to fix `settings.json` by hand; tell the user what the error says to do.
