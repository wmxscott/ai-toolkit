import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="the watcher uses kqueue and theme-monitor, macOS only"
)

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "theme_sync.py"
# The watcher reacts to kqueue events; this bounds how long a reaction may take.
FAST = 0.1


def assert_silent(result):
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def elapsed_until(sandbox, predicate, timeout=5.0):
    started = time.monotonic()
    assert sandbox.wait_for(predicate, timeout=timeout)
    return time.monotonic() - started


def cpu_seconds(pid):
    out = subprocess.run(
        ["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True, check=True
    ).stdout.strip()
    minutes, _, seconds = out.rpartition(":")
    return 60 * int(minutes or 0) + float(seconds)


@pytest.fixture
def running(sandbox):
    """theme-monitor's trigger at dark, setup done, one session and its watcher."""
    sandbox.set_trigger("dark")
    sandbox.enable()
    claude = sandbox.start_claude()
    pid = sandbox.one_watcher()
    assert sandbox.wait_for(lambda: sandbox.base() == "dark")
    return claude, pid


def test_hook_is_quick_silent_and_starts_a_watcher(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    started = time.monotonic()
    result = sandbox.hook()
    elapsed = time.monotonic() - started
    assert_silent(result)
    assert elapsed < 1, elapsed
    assert sandbox.base() == "dark"
    pid = sandbox.one_watcher()
    assert sandbox.wait_for(lambda: sandbox.pidfile() == str(pid))
    assert sandbox.clients() == [os.getpid()]


def test_hook_does_nothing_before_setup(sandbox):
    sandbox.set_trigger("dark")
    assert_silent(sandbox.hook())
    assert not sandbox.theme.exists()
    assert not sandbox.data.exists()
    time.sleep(0.2)
    assert sandbox.watchers() == []


@pytest.mark.parametrize("content", [None, "", "sepia"])
def test_hook_does_nothing_without_theme_monitor(sandbox, content):
    sandbox.enable()
    if content is not None:
        sandbox.set_trigger(content)
    before = sandbox.theme.read_bytes()
    assert_silent(sandbox.hook())
    assert sandbox.theme.read_bytes() == before
    assert not sandbox.data.exists()
    time.sleep(0.2)
    assert sandbox.watchers() == []


def test_override_syncs_once_without_a_watcher(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    assert_silent(sandbox.hook(CLAUDE_THEME_SYNC_THEME="light"))
    assert sandbox.base() == "light"
    time.sleep(0.2)
    assert sandbox.watchers() == []


def test_registers_the_claude_process_not_the_shells(sandbox, running):
    claude, _ = running
    assert sandbox.clients() == [claude.pid]


def test_in_place_trigger_writes_apply_at_once(sandbox, running):
    for value in ("light", "dark", "light"):
        sandbox.set_trigger(value)
        took = elapsed_until(sandbox, lambda v=value: sandbox.base() == v)
        assert took < FAST, (value, took)


def test_keeps_name_and_overrides(sandbox):
    sandbox.enable({"name": "Mine", "base": "light", "overrides": {"claude": "#bd93f9"}})
    sandbox.set_trigger("dark")
    sandbox.start_claude()
    assert sandbox.wait_for(lambda: sandbox.base() == "dark")
    assert sandbox.read_theme() == {
        "name": "Mine",
        "base": "dark",
        "overrides": {"claude": "#bd93f9"},
    }
    assert [p.name for p in sandbox.theme.parent.iterdir()] == ["theme-sync.json"]


def test_writes_only_when_the_theme_changes(sandbox, running):
    before = os.stat(sandbox.theme)
    sandbox.set_trigger("dark")
    sandbox.set_trigger("dark\n")
    time.sleep(0.2)
    after = os.stat(sandbox.theme)
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_follows_a_trigger_that_is_deleted_and_recreated(sandbox, running):
    sandbox.trigger.unlink()
    time.sleep(0.05)
    assert sandbox.base() == "dark"
    sandbox.set_trigger("light")
    assert elapsed_until(sandbox, lambda: sandbox.base() == "light") < FAST
    sandbox.set_trigger("dark")
    assert elapsed_until(sandbox, lambda: sandbox.base() == "dark") < FAST


def test_follows_a_trigger_that_is_replaced(sandbox, running):
    sandbox.replace_trigger("light")
    assert elapsed_until(sandbox, lambda: sandbox.base() == "light") < FAST
    sandbox.set_trigger("dark")
    assert elapsed_until(sandbox, lambda: sandbox.base() == "dark") < FAST


def test_ignores_unusable_trigger_contents(sandbox, running):
    _, pid = running
    sandbox.set_trigger("sepia")
    time.sleep(0.2)
    assert sandbox.base() == "dark"
    assert sandbox.watchers() == [pid]


def test_exits_as_soon_as_its_claude_exits(sandbox, running, ts):
    claude, _ = running
    sandbox.stop_claude(claude)
    assert elapsed_until(sandbox, lambda: sandbox.watchers() == []) < 1
    assert sandbox.clients() == []
    fd = ts.try_lock(str(sandbox.data))
    assert fd is not None
    os.close(fd)


def test_stays_until_the_last_of_several_clients_exits(sandbox, running):
    first, pid = running
    second = sandbox.start_claude()
    third = sandbox.start_claude()
    assert sandbox.clients() == sorted([first.pid, second.pid, third.pid])
    sandbox.stop_claude(first)
    sandbox.stop_claude(third)
    assert sandbox.wait_for(lambda: sandbox.clients() == [second.pid])
    time.sleep(0.2)
    assert sandbox.watchers() == [pid]
    sandbox.set_trigger("light")
    assert sandbox.wait_for(lambda: sandbox.base() == "light", timeout=1)
    sandbox.stop_claude(second)
    assert elapsed_until(sandbox, lambda: sandbox.watchers() == []) < 1


def test_no_duplicate_watchers(sandbox, running):
    _, first = running
    for _ in range(3):
        sandbox.start_claude()
    threads = [threading.Thread(target=sandbox.hook) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(0.3)
    assert sandbox.watchers() == [first]
    assert sandbox.pidfile() == str(first)


def test_concurrent_first_starts_leave_one_watcher(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    threads = [threading.Thread(target=sandbox.hook) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    pid = sandbox.one_watcher()
    time.sleep(0.3)
    assert sandbox.watchers() == [pid]


def test_a_new_session_starts_a_new_watcher(sandbox, running):
    claude, old = running
    sandbox.stop_claude(claude)
    assert sandbox.wait_for(lambda: sandbox.watchers() == [])
    sandbox.start_claude()
    new = sandbox.one_watcher()
    assert new != old


def test_exits_when_the_theme_file_is_deleted(sandbox, running):
    sandbox.theme.unlink()
    assert sandbox.wait_for(lambda: sandbox.watchers() == [], timeout=5)
    assert not sandbox.theme.exists()


def test_survives_an_editor_style_save_of_the_theme_file(sandbox, running):
    _, pid = running
    backup = sandbox.theme.with_name("theme-sync.json~")
    os.rename(sandbox.theme, backup)
    time.sleep(0.3)
    sandbox.theme.write_text('{"base": "dark", "overrides": {"claude": "#ff0000"}}')
    backup.unlink()
    time.sleep(2.5)
    assert sandbox.watchers() == [pid]
    sandbox.set_trigger("light")
    assert sandbox.wait_for(lambda: sandbox.base() == "light", timeout=1)
    assert sandbox.read_theme()["overrides"] == {"claude": "#ff0000"}


def test_exits_when_the_data_dir_is_removed(sandbox, running):
    shutil.rmtree(sandbox.data)
    assert elapsed_until(sandbox, lambda: sandbox.watchers() == []) < 1


def test_exits_when_theme_monitor_folder_is_removed(sandbox, running):
    shutil.rmtree(sandbox.trigger.parent)
    assert elapsed_until(sandbox, lambda: sandbox.watchers() == []) < 1


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
    sandbox.set_trigger("dark")
    fd = ts.try_lock(str(sandbox.data))
    try:
        proc = run_watch(sandbox)
        out, err = proc.communicate(timeout=5)
    finally:
        os.close(fd)
    assert (proc.returncode, out, err) == (0, b"", b"")


def test_watch_ignores_a_reused_pid(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    clients = sandbox.data / "clients"
    clients.mkdir(parents=True)
    (clients / str(os.getpid())).write_text("Mon Jan  1 00:00:00 2024\n")
    proc = run_watch(sandbox)
    assert proc.wait(timeout=5) == 0
    assert sandbox.clients() == []


def test_watch_without_clients_exits(sandbox):
    sandbox.enable()
    sandbox.set_trigger("dark")
    assert run_watch(sandbox).wait(timeout=5) == 0


def test_idle_watcher_uses_no_cpu(sandbox, running):
    _, pid = running
    time.sleep(0.5)
    before = cpu_seconds(pid)
    time.sleep(3)
    assert cpu_seconds(pid) - before < 0.01


@pytest.mark.parametrize("missing", ["CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA"])
def test_hook_does_nothing_without_plugin_env(sandbox, missing):
    sandbox.enable()
    sandbox.set_trigger("dark")
    env = {k: v for k, v in sandbox.env.items() if k != missing}
    result = subprocess.run(
        ["bash", str(PLUGIN / "scripts" / "session_start.sh")],
        env=env,
        capture_output=True,
        timeout=10,
    )
    assert_silent(result)
    time.sleep(0.2)
    assert sandbox.watchers() == []


def test_hook_does_nothing_without_python(sandbox, tmp_path):
    sandbox.enable()
    sandbox.set_trigger("dark")
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "bash").symlink_to(shutil.which("bash", path="/usr/bin:/bin"))
    assert_silent(sandbox.hook(PATH=str(bare)))
    assert sandbox.base() == "light"


def test_hook_fails_safe_when_the_data_dir_cannot_be_created(sandbox, tmp_path):
    sandbox.enable()
    sandbox.set_trigger("dark")
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert_silent(sandbox.hook(CLAUDE_PLUGIN_DATA=str(blocker / "data")))
    time.sleep(0.2)
    assert sandbox.watchers() == []
