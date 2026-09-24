import contextlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN / "scripts"
HOOK = SCRIPTS / "session_start.sh"

FAKE_CLAUDE = """
import subprocess, sys
subprocess.run(["sh", "-c", 'bash "$0"', sys.argv[1]], stdin=subprocess.DEVNULL)
print("ready", flush=True)
sys.stdin.read()
"""


def wait_for(predicate, timeout=10.0, interval=0.002):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


def load_module(monkeypatch, name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ts(monkeypatch):
    return load_module(monkeypatch, "theme_sync", SCRIPTS / "theme_sync.py")


class Sandbox:
    """A scratch $HOME, and every process started from it."""

    wait_for = staticmethod(wait_for)

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.claude = self.home / ".claude"
        self.theme = self.claude / "themes" / "theme-sync.json"
        self.settings = self.claude / "settings.json"
        self.data = self.claude / "plugins" / "data" / "theme-sync-ai-toolkit"
        self.trigger = self.home / ".local" / "share" / "theme-monitor" / "theme-change.trigger"
        self.env = {
            "HOME": str(self.home),
            "PATH": "/usr/bin:/bin",
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
            "CLAUDE_PLUGIN_DATA": str(self.data),
        }
        self.procs: list[subprocess.Popen] = []

    def set_trigger(self, value: str):
        """Write the trigger file in place, keeping its inode, as theme-monitor does."""
        self.trigger.parent.mkdir(parents=True, exist_ok=True)
        with open(self.trigger, "r+" if self.trigger.exists() else "w") as f:
            f.truncate(0)
            f.write(value)

    def replace_trigger(self, value: str):
        tmp = self.trigger.with_name("new.tmp")
        tmp.write_text(value)
        os.replace(tmp, self.trigger)

    def enable(self, content=None):
        self.theme.parent.mkdir(parents=True, exist_ok=True)
        self.theme.write_text(json.dumps(content or {"base": "light"}))

    def read_theme(self):
        try:
            return json.loads(self.theme.read_text())
        except (OSError, ValueError):
            return None

    def base(self):
        return (self.read_theme() or {}).get("base")

    def hook(self, **extra):
        return subprocess.run(
            ["bash", str(HOOK)],
            env={**self.env, **extra},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
        )

    def start_claude(self, **extra):
        """A stand-in Claude Code process that runs the hook, then lives until stopped."""
        proc = subprocess.Popen(
            [sys.executable, "-c", FAKE_CLAUDE, str(HOOK)],
            env={**self.env, **extra},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.procs.append(proc)
        assert proc.stdout.readline().strip() == "ready"
        return proc

    def stop_claude(self, proc):
        proc.stdin.close()
        proc.wait(timeout=10)

    def watchers(self):
        out = subprocess.run(
            ["ps", "-A", "-ww", "-o", "pid=,args="], capture_output=True, text=True, check=True
        ).stdout
        marker = f"theme_sync.py watch {self.root}"
        pids = []
        for line in out.splitlines():
            pid, _, args = line.strip().partition(" ")
            if marker in args:
                pids.append(int(pid))
        return pids

    def one_watcher(self):
        found = self.wait_for(lambda: len(self.watchers()) == 1 and self.watchers())
        assert found, self.watchers()
        return found[0]

    def clients(self):
        folder = self.data / "clients"
        return sorted(int(p.name) for p in folder.iterdir()) if folder.is_dir() else []

    def pidfile(self):
        try:
            return (self.data / "watcher.pid").read_text().strip()
        except OSError:
            return None

    def cleanup(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            for stream in (proc.stdin, proc.stdout):
                if stream:
                    stream.close()
        for pid in self.watchers():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)


@pytest.fixture
def sandbox(tmp_path):
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()
