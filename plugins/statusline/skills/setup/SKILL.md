---
name: setup
description: Sets Claude Code's statusLine setting to run the statusline plugin. Run once after installing the plugin.
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_statusline.py *)
---

Point the user's `statusLine` setting at the statusline plugin. The bundled script does all the work: it links a stable copy of the statusline into the plugin's data directory and edits `settings.json` safely. Never edit `settings.json` yourself.

1. Run:

   ```sh
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_statusline.py "${CLAUDE_PLUGIN_DATA}"
   ```

2. Act on its exit status:
   - **0**: done, or already set up. Show the user the script's output, and tell them the statusline appears within a second or two.
   - **3**: the user already has a different `statusLine`. Nothing has changed yet. Show them the current and proposed values from the output and ask whether to replace the current one. Only if they say yes, run the same command again with `--force` added. If they say no, stop and change nothing.
   - **Anything else**: show the error. Don't try to fix `settings.json` by hand; tell the user what the error says to do.
