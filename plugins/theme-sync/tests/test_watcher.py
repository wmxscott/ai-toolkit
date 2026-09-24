import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "theme_sync.py"


def assert_silent(result):
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def one_watcher(sandbox):
    return sandbox.wait_for(lambda: len(sandbox.watchers()) == 1 and sandbox.watchers()[0])


def test_hook_does_nothing_before_setup(sandbox):
    sandbox.set_trigger("dark")
    assert_silent(sandbox.hook())
    assert not sandbox.theme.exists()
    assert not sandbox.data.exists()
    time.sleep(0.3)
    assert sandbox.watchers() == []


def test_hook_is_quick_silent_and_starts_a_watcher(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    started = time.monotonic()
    result = sandbox.hook()
    elapsed = time.monotonic() - started
    assert_silent(result)
    assert elapsed < 3, elapsed
    assert sandbox.base() == "dark"
    pid = one_watcher(sandbox)
    assert pid
    assert sandbox.wait_for(lambda: sandbox.pidfile() == str(pid))
    assert sandbox.clients() == [os.getpid()]


def test_registers_the_claude_process_not_the_shells(sandbox):
    sandbox.enable()
    claude = sandbox.start_claude()
    assert sandbox.clients() == [claude.pid]
    assert one_watcher(sandbox)


def test_follows_the_trigger_file_live(sandbox):
    sandbox.enable({"name": "Mine", "base": "dark", "overrides": {"claude": "#bd93f9"}})
    sandbox.set_trigger("dark")
    sandbox.start_claude()
    assert one_watcher(sandbox)
    sandbox.set_trigger("light")
    assert sandbox.wait_for(lambda: sandbox.base() == "light")
    sandbox.set_trigger("dark")
    assert sandbox.wait_for(lambda: sandbox.base() == "dark")
    assert sandbox.read_theme() == {
        "name": "Mine",
        "base": "dark",
        "overrides": {"claude": "#bd93f9"},
    }
    leftovers = [p.name for p in sandbox.theme.parent.iterdir() if p.name != "theme-sync.json"]
    assert leftovers == []


def test_writes_only_when_the_theme_changes(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    sandbox.start_claude()
    assert sandbox.wait_for(lambda: sandbox.base() == "dark")
    before = os.stat(sandbox.theme)
    time.sleep(0.5)
    after = os.stat(sandbox.theme)
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the macOS appearance")
def test_follows_the_macos_appearance_without_theme_monitor(sandbox):
    sandbox.enable()
    sandbox.set_appearance(True)
    sandbox.start_claude()
    assert sandbox.wait_for(lambda: sandbox.base() == "dark")
    sandbox.set_appearance(False)
    assert sandbox.wait_for(lambda: sandbox.base() == "light")


def test_no_duplicate_watchers(sandbox):
    sandbox.enable()
    sandbox.start_claude()
    first = one_watcher(sandbox)
    for _ in range(3):
        sandbox.start_claude()
    threads = [threading.Thread(target=sandbox.hook) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(0.5)
    assert sandbox.watchers() == [first]
    assert sandbox.pidfile() == str(first)


def test_concurrent_first_starts_leave_one_watcher(sandbox):
    sandbox.enable()
    threads = [threading.Thread(target=sandbox.hook) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    pid = one_watcher(sandbox)
    time.sleep(0.5)
    assert sandbox.watchers() == [pid]


def test_exits_when_the_last_claude_exits(sandbox, ts):
    sandbox.enable()
    first = sandbox.start_claude()
    second = sandbox.start_claude()
    pid = one_watcher(sandbox)
    sandbox.stop_claude(first)
    time.sleep(0.6)
    assert sandbox.watchers() == [pid]
    assert sandbox.wait_for(lambda: sandbox.clients() == [second.pid])
    sandbox.stop_claude(second)
    assert sandbox.wait_for(lambda: sandbox.watchers() == [])
    assert sandbox.clients() == []
    fd = ts.try_lock(str(sandbox.data))
    assert fd is not None
    os.close(fd)


def test_a_new_session_starts_a_new_watcher(sandbox):
    sandbox.enable()
    first = sandbox.start_claude()
    old = one_watcher(sandbox)
    sandbox.stop_claude(first)
    assert sandbox.wait_for(lambda: sandbox.watchers() == [])
    sandbox.start_claude()
    new = one_watcher(sandbox)
    assert new and new != old


def test_exits_when_the_theme_file_is_deleted(sandbox):
    sandbox.enable()
    sandbox.start_claude()
    assert one_watcher(sandbox)
    sandbox.theme.unlink()
    assert sandbox.wait_for(lambda: sandbox.watchers() == [])
    assert not sandbox.theme.exists()


def test_exits_when_the_data_dir_is_removed(sandbox):
    sandbox.enable()
    sandbox.start_claude()
    assert one_watcher(sandbox)
    shutil.rmtree(sandbox.data)
    assert sandbox.wait_for(lambda: sandbox.watchers() == [])


def test_override_syncs_once_without_a_watcher(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    assert_silent(sandbox.hook(CLAUDE_THEME_SYNC_THEME="light"))
    assert sandbox.base() == "light"
    time.sleep(0.3)
    assert sandbox.watchers() == []


def run_watch(sandbox):
    return subprocess.Popen(
        [sys.executable, str(SCRIPT), "watch", str(sandbox.data)],
        env=sandbox.env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_watch_exits_at_once_when_another_holds_the_lock(sandbox, ts):
    sandbox.enable()
    fd = ts.try_lock(str(sandbox.data))
    try:
        proc = run_watch(sandbox)
        out, err = proc.communicate(timeout=5)
    finally:
        os.close(fd)
    assert (proc.returncode, out, err) == (0, b"", b"")


def test_watch_ignores_a_reused_pid(sandbox, ts):
    sandbox.enable()
    clients = sandbox.data / "clients"
    clients.mkdir(parents=True)
    (clients / str(os.getpid())).write_text("Mon Jan  1 00:00:00 2024\n")
    proc = run_watch(sandbox)
    assert proc.wait(timeout=5) == 0
    assert sandbox.clients() == []


def test_watch_without_clients_exits(sandbox):
    sandbox.enable()
    proc = run_watch(sandbox)
    assert proc.wait(timeout=5) == 0


def test_watcher_sleeps_between_checks(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    sandbox.hook(CLAUDE_THEME_SYNC_TICK="1")
    pid = one_watcher(sandbox)
    time.sleep(3)
    cputime = subprocess.run(
        ["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.strip()
    *_, minutes, seconds = cputime.replace("-", ":").split(":")
    assert 60 * int(minutes) + float(seconds) < 0.5, cputime


@pytest.mark.parametrize("missing", ["CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA"])
def test_hook_does_nothing_without_plugin_env(sandbox, missing):
    sandbox.enable()
    env = {k: v for k, v in sandbox.env.items() if k != missing}
    result = subprocess.run(
        ["bash", str(PLUGIN / "scripts" / "session_start.sh")],
        env=env,
        capture_output=True,
        timeout=10,
    )
    assert_silent(result)
    time.sleep(0.3)
    assert sandbox.watchers() == []


def test_hook_does_nothing_without_python(sandbox, tmp_path):
    sandbox.enable()
    bare = tmp_path / "bare"
    bare.mkdir()
    for tool in ("bash", "dirname"):
        found = shutil.which(tool, path="/usr/bin:/bin")
        if found:
            (bare / tool).symlink_to(found)
    assert_silent(sandbox.hook(PATH=str(bare)))
    assert json.loads(sandbox.theme.read_text()) == {"base": "light"}


def test_hook_fails_safe_when_the_data_dir_cannot_be_created(sandbox, tmp_path):
    sandbox.enable()
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert_silent(sandbox.hook(CLAUDE_PLUGIN_DATA=str(blocker / "data")))
    time.sleep(0.3)
    assert sandbox.watchers() == []
