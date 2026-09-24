#!/usr/bin/env python3
"""Point Claude Code's statusLine setting at the plugin's stable script path.

Links DATA_DIR/statusline.py to this plugin version's script, then sets
statusLine in settings.json, keeping every other key. A symlinked
settings.json is written through to its target.

Exit status: 0 done or already set, 1 error, 3 a different statusLine is set
and --force was not given.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANAGED_KEYS = ("type", "command", "padding", "refreshInterval")
EXIT_CONFLICT = 3


class SetupError(Exception):
    pass


def default_settings_path() -> str:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return os.path.join(config_dir, "settings.json")


def shell_command(script: str) -> str:
    home = os.path.expanduser("~")
    prefix = ""
    if script.startswith(home + os.sep):
        prefix, script = "$HOME", script[len(home) :]
    for ch in '\\"$`':
        script = script.replace(ch, "\\" + ch)
    return f'python3 "{prefix}{script}"'


def link_script(data_dir: str) -> str:
    target = os.path.join(PLUGIN_ROOT, "scripts", "statusline.py")
    link = os.path.join(data_dir, "statusline.py")
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT, "CLAUDE_PLUGIN_DATA": data_dir}
    subprocess.run(
        ["bash", os.path.join(PLUGIN_ROOT, "scripts", "link_statusline.sh")],
        env=env,
        check=False,
    )
    if not (os.path.islink(link) and os.readlink(link) == target):
        raise SetupError(f"could not link {link} to {target}")
    return link


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


def write(path: str, data: dict) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def show(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def setup(data_dir: str, settings: str, force: bool) -> int:
    if not os.path.isabs(data_dir):
        raise SetupError(f"data dir must be an absolute path, got {data_dir!r}")
    link = link_script(data_dir)
    print(f"Linked {link} -> {os.readlink(link)}")

    target = os.path.realpath(settings)
    via = f" (through the symlink {settings})" if os.path.islink(settings) else ""
    data = load(target)
    current = data.get("statusLine")
    extras = {}
    if isinstance(current, dict):
        extras = {k: v for k, v in current.items() if k not in MANAGED_KEYS}
    desired = {
        "type": "command",
        "command": shell_command(link),
        "padding": 0,
        "refreshInterval": 1,
        **extras,
    }

    if current == desired:
        print(f"statusLine in {target} already runs this statusline. Nothing changed.")
        return 0
    if current is not None and not force:
        print(f"{target}{via} already has a different statusLine:")
        print(show(current))
        print("Proposed:")
        print(show(desired))
        print("Nothing changed. Run again with --force to replace it.")
        return EXIT_CONFLICT

    data["statusLine"] = desired
    write(target, data)
    print(f"Updated {target}{via}.")
    if current is not None:
        print("Old statusLine:")
        print(show(current))
    print("New statusLine:")
    print(show(desired))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", help="the plugin's persistent data dir, ${CLAUDE_PLUGIN_DATA}")
    parser.add_argument("--settings", default=default_settings_path(), help="settings.json to edit")
    parser.add_argument("--force", action="store_true", help="replace a different statusLine")
    args = parser.parse_args(argv)
    try:
        return setup(args.data_dir, args.settings, args.force)
    except (SetupError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
