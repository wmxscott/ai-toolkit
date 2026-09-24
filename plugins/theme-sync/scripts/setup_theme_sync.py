#!/usr/bin/env python3
"""Point Claude Code's theme setting at the theme-sync theme.

Needs macOS and theme-monitor. Writes the theme file, then sets
"theme": "custom:theme-sync" in settings.json, keeping every other key, and
starts the watcher. A symlinked settings.json is written through to its target.

Exit status: 0 done or already set, 1 error, 3 a different theme is set and
--force was not given, 4 theme-monitor isn't running.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import theme_sync

EXIT_CONFLICT = 3
EXIT_NO_THEME_MONITOR = 4
INSTALL_THEME_MONITOR = (
    "brew install wmxscott/tap/theme-monitor && brew services start theme-monitor"
)


class SetupError(Exception):
    pass


def default_settings_path() -> str:
    return os.path.join(theme_sync.config_dir(), "settings.json")


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise SetupError(f"cannot read {path}: {exc}") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SetupError(f"{path} is not valid JSON ({exc}); fix it and run setup again") from exc
    if not isinstance(data, dict):
        raise SetupError(f"{path} does not hold a JSON object")
    return data


def setup(data_dir: str, settings: str, force: bool) -> int:
    if not os.path.isabs(data_dir):
        raise SetupError(f"data dir must be an absolute path, got {data_dir!r}")
    if not theme_sync.supported():
        raise SetupError("theme-sync works on macOS only")
    trigger = theme_sync.trigger_theme()
    if trigger is None:
        print(f"theme-sync needs theme-monitor, and {theme_sync.trigger_path()} isn't there.")
        print("Install and start it, then run setup again:")
        print(f"  {INSTALL_THEME_MONITOR}")
        print("Nothing changed.")
        return EXIT_NO_THEME_MONITOR
    target = os.path.realpath(settings)
    via = f" (through the symlink {settings})" if os.path.islink(settings) else ""
    data = load(target)
    current = data.get("theme")
    desired = theme_sync.SETTING

    if current is not None and current != desired and not force:
        print(f"{target}{via} already sets a different theme: {json.dumps(current)}")
        print(f"Proposed: {json.dumps(desired)}")
        print("Nothing changed. Run again with --force to replace it.")
        return EXIT_CONFLICT

    themes_dir = os.path.dirname(theme_sync.theme_path())
    new_dir = not os.path.isdir(themes_dir)
    theme = theme_sync.override_theme() or trigger
    theme_sync.sync(theme)
    print(f"Theme file {theme_sync.theme_path()} follows the appearance, now {theme}.")

    if current == desired:
        print(f"theme in {target} is already {json.dumps(desired)}. Nothing changed.")
    else:
        data["theme"] = desired
        theme_sync.atomic_write(target, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"Updated {target}{via}.")
        if current is not None:
            print(f"Old theme: {json.dumps(current)}")
        print(f"New theme: {json.dumps(desired)}")

    try:
        theme_sync.start(data_dir)
    except Exception as exc:
        print(f"Could not start the watcher now ({exc}); it starts with the next session.")
    if new_dir:
        print(f"{themes_dir} is new: restart Claude Code once so it starts watching it.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", help="the plugin's persistent data dir, ${CLAUDE_PLUGIN_DATA}")
    parser.add_argument("--settings", default=default_settings_path(), help="settings.json to edit")
    parser.add_argument("--force", action="store_true", help="replace a different theme")
    args = parser.parse_args(argv)
    try:
        return setup(args.data_dir, args.settings, args.force)
    except (SetupError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
