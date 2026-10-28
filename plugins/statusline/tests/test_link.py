import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
HOOK = PLUGIN / "scripts" / "link_statusline.sh"

NOTICE = {"systemMessage": "statusline: run /statusline:setup to switch to the faster version"}
URL = "https://github.com/wmxscott/ai-toolkit/releases/download"
OLD = 'python3 "$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline.py"'


def run_hook(env, *args):
    return subprocess.run(
        ["/bin/bash", str(HOOK), *args], env=env, capture_output=True, timeout=10, input=b"{}"
    )


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def data(home):
    return home / ".claude" / "plugins" / "data" / "statusline-ai-toolkit"


def hook(release, data, home, *args, **extra):
    return run_hook(release.env(data, HOME=str(home), **extra), *args)


def assert_silent_success(result):
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def installed(data):
    return sorted(p.name for p in (data / "bin").iterdir()) if (data / "bin").exists() else []


def binary(data, version="2.0.0", platform="darwin-arm64"):
    return data / "bin" / f"statusline-{version}-{platform}"


def test_downloads_verifies_and_links_in_the_foreground(release, data, home):
    assert_silent_success(hook(release, data, home, "--foreground"))
    target = binary(data)
    assert installed(data) == [target.name]
    assert os.access(target, os.X_OK)
    assert os.readlink(data / "statusline") == str(target)
    assert target.read_bytes() == release.binary("darwin", "arm64", "2.0.0")
    [call] = release.curl_calls()
    args = call.split()
    assert args[:4] == ["-fsSL", "--max-time", "30", "-o"]
    assert args[5:] == [f"{URL}/statusline-v2.0.0/statusline-darwin-arm64"]
    assert sorted(p.name for p in data.iterdir()) == ["bin", "statusline"]


@pytest.mark.parametrize(
    ("system", "machine", "platform"),
    [
        ("Darwin", "arm64", "darwin-arm64"),
        ("Darwin", "x86_64", "darwin-amd64"),
        ("Linux", "aarch64", "linux-arm64"),
        ("Linux", "arm64", "linux-arm64"),
        ("Linux", "x86_64", "linux-amd64"),
    ],
)
def test_picks_the_binary_for_the_platform(release, data, home, system, machine, platform):
    release.uname(system, machine)
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert installed(data) == [f"statusline-2.0.0-{platform}"]
    os_, arch = platform.split("-")
    assert binary(data, platform=platform).read_bytes() == release.binary(os_, arch, "2.0.0")


@pytest.mark.parametrize(("system", "machine"), [("FreeBSD", "amd64"), ("Linux", "i686")])
def test_does_nothing_on_an_unsupported_platform(release, data, home, system, machine):
    release.uname(system, machine)
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert not data.exists()
    assert release.curl_calls() == []


def test_downloads_in_the_background_without_waiting(release, data, home):
    release.curl(delay=5)
    start = time.monotonic()
    result = hook(release, data, home)
    elapsed = time.monotonic() - start
    assert_silent_success(result)
    assert elapsed < 1, elapsed
    assert not (data / "statusline").exists()
    deadline = time.monotonic() + 15
    while not (data / "statusline").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert os.readlink(data / "statusline") == str(binary(data))
    assert installed(data) == [binary(data).name]


def test_links_an_existing_binary_without_downloading(release, data, home):
    hook(release, data, home, "--foreground")
    (data / "statusline").unlink()
    assert_silent_success(hook(release, data, home))
    assert os.readlink(data / "statusline") == str(binary(data))
    assert len(release.curl_calls()) == 1


def test_is_idempotent(release, data, home):
    hook(release, data, home, "--foreground")
    before = os.lstat(data / "statusline")
    assert_silent_success(hook(release, data, home))
    after = os.lstat(data / "statusline")
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_an_update_swaps_the_link_and_removes_the_old_binary(release, data, home):
    hook(release, data, home, "--foreground")
    release.publish("2.1.0")
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert installed(data) == ["statusline-2.1.0-darwin-arm64"]
    assert os.readlink(data / "statusline") == str(binary(data, "2.1.0"))


def test_rejects_a_checksum_mismatch_and_keeps_the_old_binary(release, data, home):
    hook(release, data, home, "--foreground")
    release.publish("2.1.0")
    (release.serve / "statusline-v2.1.0" / "statusline-darwin-arm64").write_text("tampered")
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert installed(data) == [binary(data).name]
    assert os.readlink(data / "statusline") == str(binary(data))


def test_gives_up_when_the_platform_has_no_checksum(release, data, home):
    (release.root / "checksums.txt").write_text("")
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert installed(data) == []
    assert not (data / "statusline").exists()


def test_gives_up_when_the_download_fails(release, data, home):
    shutil.rmtree(release.serve)
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert installed(data) == []
    assert not (data / "statusline").exists()


def test_falls_back_to_sha256sum(release, data, home):
    release.remove("shasum")
    release.sha("sha256sum")
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert os.readlink(data / "statusline") == str(binary(data))


@pytest.mark.parametrize("missing", ["curl", "shasum"])
def test_does_nothing_without_a_tool(release, data, home, missing):
    release.remove(missing)
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert installed(data) == []
    assert not (data / "statusline").exists()


def test_skips_while_another_download_holds_the_lock(release, data, home):
    lock = data / "bin" / ".download.lock"
    lock.mkdir(parents=True)
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert release.curl_calls() == []
    assert lock.is_dir()


def test_breaks_a_stale_lock(release, data, home):
    lock = data / "bin" / ".download.lock"
    lock.mkdir(parents=True)
    old = time.time() - 300
    os.utime(lock, (old, old))
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert installed(data) == [binary(data).name]
    assert not lock.exists()


def test_does_nothing_without_a_version(release, data, home):
    manifest = release.root / ".claude-plugin" / "plugin.json"
    manifest.write_text(json.dumps({"name": "statusline"}))
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert not data.exists()


@pytest.mark.parametrize("missing", ["CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA"])
def test_does_nothing_without_plugin_env(release, data, home, missing):
    env = release.env(data, HOME=str(home))
    del env[missing]
    assert_silent_success(run_hook(env, "--foreground"))
    assert not data.exists()


def test_fails_safe_when_the_data_dir_cannot_be_created(release, home, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert_silent_success(hook(release, blocker / "data", home, "--foreground"))


def test_leaves_the_old_script_link_alone(release, data, home):
    data.mkdir(parents=True)
    (data / "statusline.py").symlink_to("/nowhere/statusline.py")
    assert_silent_success(hook(release, data, home, "--foreground"))
    assert os.readlink(data / "statusline.py") == "/nowhere/statusline.py"


def write_settings(path, command):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"statusLine": {"type": "command", "command": command}}))


@pytest.mark.parametrize("args", [(), ("--foreground",)])
def test_tells_an_old_setup_to_rerun_setup(release, data, home, args):
    write_settings(home / ".claude" / "settings.json", OLD)
    result = hook(release, data, home, *args)
    assert result.returncode == 0
    assert result.stderr == b""
    assert json.loads(result.stdout) == NOTICE
    assert result.stdout.count(b"\n") == 1


def test_notice_reads_through_a_symlinked_settings_file(release, home, tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    write_settings(real, OLD)
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").symlink_to(real)
    result = run_hook({"PATH": str(release.tools), "HOME": str(home)})
    assert json.loads(result.stdout) == NOTICE


def test_notice_honours_claude_config_dir(release, home, tmp_path):
    config = tmp_path / "config"
    env = {"PATH": str(release.tools), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(config)}
    write_settings(config / "settings.json", OLD)
    assert json.loads(run_hook(env).stdout) == NOTICE
    write_settings(config / "settings.json", '"$HOME/.claude/x/statusline"')
    write_settings(home / ".claude" / "settings.json", OLD)
    assert_silent_success(run_hook(env))


def test_no_notice_for_a_new_setup(release, home):
    write_settings(
        home / ".claude" / "settings.json",
        '"$HOME/.claude/plugins/data/statusline-ai-toolkit/statusline"',
    )
    assert_silent_success(run_hook({"PATH": str(release.tools), "HOME": str(home)}))


def test_shellcheck():
    shellcheck = shutil.which("shellcheck")
    if not shellcheck:
        pytest.skip("shellcheck not installed")
    scripts = sorted(str(p) for p in PLUGIN.rglob("*.sh"))
    assert scripts
    result = subprocess.run([shellcheck, *scripts], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
