#!/usr/bin/env python3
"""Keep the Claude Code theme `custom:theme-sync` in step with theme-monitor.

  theme_sync.py start DATA_DIR   sync once, then make sure a watcher is running
  theme_sync.py watch DATA_DIR   the watcher itself; `start` launches it

The theme comes from $CLAUDE_THEME_SYNC_THEME, else theme-monitor's trigger
file. With neither, nothing happens. macOS only: anywhere else both commands
are silent no-ops.

One watcher runs per data dir. It holds an exclusive lock on DATA_DIR/watcher.pid
for its whole life and sleeps in kqueue until the trigger file changes, a
registered Claude Code process exits, or a client registers in DATA_DIR/clients.
It exits once no registered client is left, or when the theme file, the data
dir or theme-monitor's folder goes away.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import select
import subprocess
import sys
import tempfile
import time

SLUG = "theme-sync"
SETTING = f"custom:{SLUG}"
NAME = "Theme sync"
THEMES = ("dark", "light")
OVERRIDE_ENV = "CLAUDE_THEME_SYNC_THEME"
PIDFILE = "watcher.pid"
CLIENTS = "clients"
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish", "tcsh", "csh", "nu", "env"}
# Editors that save by moving the old file aside leave the theme file missing
# for a moment; only a deletion that lasts this long stops the watcher.
THEME_GRACE = 2.0


def supported() -> bool:
    return sys.platform == "darwin" and hasattr(select, "kqueue")


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
            ["ps", "-ww", "-o", fields, "-p", ",".join(map(str, pids))],
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
    """Record a client with its start time. The rename also wakes a running watcher."""
    started = start_times([pid]).get(pid)
    if not started:
        return False
    clients = os.path.join(data, CLIENTS)
    os.makedirs(clients, exist_ok=True)
    atomic_write(os.path.join(clients, str(pid)), started + "\n")
    return True


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
    """SessionStart: sync once and make sure a watcher is running."""
    if not supported() or not os.path.isabs(data) or not os.path.isfile(theme_path()):
        return 0
    override = override_theme()
    if override:
        sync(override)
        return 0
    theme = trigger_theme()
    if theme is None:
        return 0
    sync(theme)
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


class Stop(Exception):
    pass


FILE_EVENTS = (
    select.KQ_NOTE_WRITE
    | select.KQ_NOTE_EXTEND
    | select.KQ_NOTE_ATTRIB
    | select.KQ_NOTE_DELETE
    | select.KQ_NOTE_RENAME
    | select.KQ_NOTE_REVOKE
    if supported()
    else 0
)
DIR_EVENTS = (
    select.KQ_NOTE_WRITE | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_REVOKE
    if supported()
    else 0
)
GONE = select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_REVOKE if supported() else 0
O_EVTONLY = getattr(os, "O_EVTONLY", 0x8000)


class Watcher:
    def __init__(self, data: str, lock: int):
        self.data = data
        self.clients_dir = os.path.join(data, CLIENTS)
        self.lock: int | None = lock
        self.kq = select.kqueue()
        self.roles: dict[int, str] = {}
        self.trigger_fd: int | None = None
        self.trigger_ino: int | None = None
        self.clients: set[int] = set()
        self.theme_missing_since: float | None = None

    def arm(self, path: str, role: str, events: int) -> int | None:
        try:
            fd = os.open(path, O_EVTONLY)
        except OSError:
            return None
        event = select.kevent(
            fd,
            filter=select.KQ_FILTER_VNODE,
            flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
            fflags=events,
        )
        try:
            self.kq.control([event], 0)
        except OSError:
            os.close(fd)
            return None
        self.roles[fd] = role
        return fd

    def arm_trigger(self) -> None:
        """Watch the trigger file itself, re-opening it if it was replaced."""
        try:
            ino = os.stat(trigger_path()).st_ino
        except OSError:
            ino = None
        if self.trigger_fd is not None and ino == self.trigger_ino:
            return
        self.drop_trigger()
        if ino is not None:
            self.trigger_fd = self.arm(trigger_path(), "trigger", FILE_EVENTS)
            self.trigger_ino = ino if self.trigger_fd is not None else None

    def drop_trigger(self) -> None:
        if self.trigger_fd is not None:
            self.roles.pop(self.trigger_fd, None)
            os.close(self.trigger_fd)
        self.trigger_fd = self.trigger_ino = None

    def update(self) -> None:
        theme = trigger_theme()
        if theme is not None and os.path.isfile(theme_path()):
            with contextlib.suppress(OSError):
                sync(theme)

    def rescan(self) -> None:
        try:
            present = {int(n) for n in os.listdir(self.clients_dir) if n.isdigit()}
        except OSError as exc:
            raise Stop from exc
        self.clients &= present
        new = sorted(present - self.clients)
        if not new:
            return
        recorded = {}
        for pid in new:
            with contextlib.suppress(OSError), open(os.path.join(self.clients_dir, str(pid))) as f:
                recorded[pid] = f.read().strip()
        running = start_times(new)
        for pid in new:
            if recorded.get(pid) and running.get(pid) == recorded[pid]:
                event = select.kevent(
                    pid,
                    filter=select.KQ_FILTER_PROC,
                    flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                    fflags=select.KQ_NOTE_EXIT,
                )
                try:
                    self.kq.control([event], 0)
                    self.clients.add(pid)
                    continue
                except OSError:
                    pass
            self.forget(pid)

    def forget(self, pid: int) -> None:
        self.clients.discard(pid)
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(self.clients_dir, str(pid)))

    def handoff(self) -> None:
        """No clients left: release the lock, then check once more before exiting."""
        if self.lock is not None:
            release(self.lock)
            self.lock = None
        self.rescan()
        if not self.clients:
            raise Stop
        self.lock = acquire(self.data)
        if self.lock is None:
            raise Stop

    def setup(self) -> None:
        # Arm every watch before reading what it covers, so no change is missed.
        for path, role in (
            (self.data, "data"),
            (self.clients_dir, "clients"),
            (os.path.dirname(theme_path()), "themes"),
            (os.path.dirname(trigger_path()), "trigger-dir"),
        ):
            if self.arm(path, role, DIR_EVENTS) is None:
                raise Stop
        self.arm_trigger()
        if not os.path.isfile(theme_path()):
            raise Stop
        self.rescan()
        self.update()

    def handle(self, event) -> bool:
        """Process one event. Returns whether the trigger may have changed."""
        if event.filter == select.KQ_FILTER_PROC:
            self.forget(event.ident)
            return False
        role = self.roles.get(event.ident)
        gone = bool(event.fflags & GONE)
        if role in ("data", "clients", "themes", "trigger-dir") and gone:
            raise Stop
        if role == "clients":
            self.rescan()
        elif role == "themes":
            if os.path.isfile(theme_path()):
                self.theme_missing_since = None
            elif self.theme_missing_since is None:
                self.theme_missing_since = time.monotonic()
        elif role == "trigger":
            if gone:
                self.drop_trigger()
            return True
        elif role == "trigger-dir":
            return True
        return False

    def run(self) -> None:
        self.setup()
        while True:
            if not self.clients:
                self.handoff()
            timeout = None
            if self.theme_missing_since is not None:
                timeout = max(0.0, THEME_GRACE - (time.monotonic() - self.theme_missing_since))
            events = self.kq.control(None, 32, timeout)
            if self.theme_missing_since is not None:
                if os.path.isfile(theme_path()):
                    self.theme_missing_since = None
                elif time.monotonic() - self.theme_missing_since >= THEME_GRACE:
                    raise Stop
            changed = False
            for event in events:
                changed = self.handle(event) or changed
            if changed:
                self.arm_trigger()
                self.update()

    def close(self) -> None:
        for fd in list(self.roles):
            os.close(fd)
        self.roles.clear()
        self.kq.close()
        if self.lock is not None:
            release(self.lock)
            self.lock = None


def watch(data: str) -> int:
    if not supported():
        return 0
    lock = acquire(data)
    if lock is None:
        return 0
    watcher = Watcher(data, lock)
    try:
        watcher.run()
    except Stop:
        pass
    finally:
        watcher.close()
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "start":
        try:
            return start(argv[2])
        except Exception:
            return 0
    if len(argv) == 3 and argv[1] == "watch":
        return watch(argv[2])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
