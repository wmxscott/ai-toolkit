#!/usr/bin/env python3
"""Keep the Claude Code theme `custom:theme-sync` in step with the macOS appearance.

  theme_sync.py start DATA_DIR   sync once, then make sure a watcher is running
  theme_sync.py watch DATA_DIR   the watcher itself; `start` launches it
  theme_sync.py sync             sync once and print the theme

The theme comes from the first of: $CLAUDE_THEME_SYNC_THEME, theme-monitor's
trigger file, `defaults read -g AppleInterfaceStyle`, then dark.

One watcher runs per data dir. It holds an exclusive lock on DATA_DIR/watcher.pid
for its whole life, and exits once every Claude Code process registered in
DATA_DIR/clients has ended, or the theme file has been deleted.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time

SLUG = "theme-sync"
SETTING = f"custom:{SLUG}"
NAME = "Theme sync"
THEMES = ("dark", "light")
OVERRIDE_ENV = "CLAUDE_THEME_SYNC_THEME"
TICK_ENV = "CLAUDE_THEME_SYNC_TICK"
PIDFILE = "watcher.pid"
CLIENTS = "clients"
DEFAULTS_EVERY = 2
LIVENESS_EVERY = 5
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish", "tcsh", "csh", "nu", "env"}


def config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def theme_path() -> str:
    return os.path.join(config_dir(), "themes", f"{SLUG}.json")


def trigger_path() -> str:
    return os.path.expanduser("~/.local/share/theme-monitor/theme-change.trigger")


def normalise(value: str) -> str | None:
    value = value.strip().lower()
    return value if value in THEMES else None


def override_theme() -> str | None:
    return normalise(os.environ.get(OVERRIDE_ENV, ""))


def trigger_theme() -> str | None:
    try:
        with open(trigger_path(), encoding="utf-8", errors="replace") as f:
            return normalise(f.read(64))
    except OSError:
        return None


def macos_theme() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # The key only exists in dark mode, so a failed read means light.
    return "dark" if result.returncode == 0 and result.stdout.strip() == "Dark" else "light"


def resolve() -> str:
    return override_theme() or trigger_theme() or macos_theme() or "dark"


def atomic_write(path: str, text: str) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{SLUG}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def sync(theme: str, path: str | None = None) -> bool:
    """Set the theme file's base to `theme`. Writes only on a change; returns whether it wrote."""
    path = os.path.realpath(path or theme_path())
    current: dict = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            current = data
    except (OSError, ValueError):
        pass
    if current.get("base") == theme:
        return False
    desired = {"name": NAME, **current, "base": theme}
    atomic_write(path, json.dumps(desired, indent=2, ensure_ascii=False) + "\n")
    return True


def ps(fields: str, pids: list[int]) -> list[str]:
    if not pids:
        return []
    try:
        result = subprocess.run(
            ["ps", "-o", fields, "-p", ",".join(map(str, pids))],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return result.stdout.splitlines()


def start_times(pids: list[int]) -> dict[int, str]:
    times = {}
    for line in ps("pid=,lstart=", pids):
        pid, _, started = line.strip().partition(" ")
        if pid.isdigit():
            times[int(pid)] = " ".join(started.split())
    return times


def find_client() -> int | None:
    """The Claude Code process running this hook: the nearest ancestor that isn't a shell."""
    pid = os.getppid()
    for _ in range(8):
        if pid <= 1:
            return None
        lines = ps("ppid=,comm=", [pid])
        if not lines:
            return None
        ppid, _, comm = lines[0].strip().partition(" ")
        name = os.path.basename(comm.strip()).lstrip("-")
        if name not in SHELLS:
            return pid
        if not ppid.isdigit():
            return None
        pid = int(ppid)
    return None


def register(data: str, pid: int) -> bool:
    started = start_times([pid]).get(pid)
    if not started:
        return False
    clients = os.path.join(data, CLIENTS)
    os.makedirs(clients, exist_ok=True)
    atomic_write(os.path.join(clients, str(pid)), started + "\n")
    return True


def live_clients(data: str) -> int:
    """Count registered clients still running, forgetting the rest. A reused pid doesn't count."""
    clients = os.path.join(data, CLIENTS)
    try:
        names = [n for n in os.listdir(clients) if n.isdigit()]
    except OSError:
        return 0
    recorded = {}
    for name in names:
        try:
            with open(os.path.join(clients, name), encoding="utf-8") as f:
                recorded[int(name)] = f.read().strip()
        except OSError:
            pass
    running = start_times(sorted(recorded))
    alive = 0
    for pid, started in recorded.items():
        if running.get(pid) == started:
            alive += 1
        else:
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(clients, str(pid)))
    return alive


def try_lock(data: str) -> int | None:
    try:
        os.makedirs(data, exist_ok=True)
        fd = os.open(os.path.join(data, PIDFILE), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def spawn_watcher(data: str) -> None:
    env = {k: v for k, v in os.environ.items() if k != OVERRIDE_ENV}
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "watch", data],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd="/",
        env=env,
        close_fds=True,
        start_new_session=True,
    )


def start(data: str) -> int:
    """SessionStart: sync once and make sure a watcher is running. Does nothing before setup."""
    if not os.path.isabs(data) or not os.path.isfile(theme_path()):
        return 0
    sync(resolve())
    if override_theme():
        return 0
    pid = find_client()
    if pid is None or not register(data, pid):
        return 0
    # Probe the lock after registering: a watcher that is about to exit rechecks
    # the clients once it has released the lock, so it can't miss this one.
    fd = try_lock(data)
    if fd is None:
        return 0
    os.close(fd)
    spawn_watcher(data)
    return 0


def tick() -> float:
    try:
        value = float(os.environ.get(TICK_ENV, ""))
    except ValueError:
        return 1.0
    return max(value, 0.01) if value > 0 else 1.0


def acquire(data: str) -> int | None:
    fd = try_lock(data)
    if fd is not None:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def release(fd: int) -> None:
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
    os.close(fd)


def wanted(data: str) -> bool:
    return os.path.isfile(theme_path()) and live_clients(data) > 0


def watch(data: str) -> int:
    fd = acquire(data)
    if fd is None:
        return 0
    step = tick()
    last = mac = None
    n = 0
    try:
        while True:
            if n % LIVENESS_EVERY == 0 and not wanted(data):
                release(fd)
                fd = None
                if not wanted(data):
                    return 0
                fd = acquire(data)
                if fd is None:
                    return 0
            theme = trigger_theme()
            if theme is None:
                if mac is None or n % DEFAULTS_EVERY == 0:
                    mac = macos_theme()
                theme = mac or "dark"
            else:
                mac = None
            if theme != last:
                with contextlib.suppress(OSError):
                    sync(theme)
                    last = theme
            n += 1
            time.sleep(step)
    finally:
        if fd is not None:
            release(fd)


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "start":
        try:
            return start(argv[2])
        except Exception:
            return 0
    if len(argv) == 3 and argv[1] == "watch":
        return watch(argv[2])
    if len(argv) == 2 and argv[1] == "sync":
        theme = resolve()
        sync(theme)
        print(theme)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
