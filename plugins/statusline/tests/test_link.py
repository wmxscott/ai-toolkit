import os
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
HOOK = PLUGIN / "scripts" / "link_statusline.sh"


def install(tmp_path, version):
    """A copy of the plugin as Claude Code caches it, one directory per version."""
    root = tmp_path / "cache" / "statusline" / version
    shutil.copytree(PLUGIN / "scripts", root / "scripts")
    return root


def run_hook(root, data, **extra):
    env = {"PATH": "/usr/bin:/bin", **extra}
    if root is not None:
        env["CLAUDE_PLUGIN_ROOT"] = str(root)
    if data is not None:
        env["CLAUDE_PLUGIN_DATA"] = str(data)
    return subprocess.run(
        ["bash", str(HOOK)], env=env, capture_output=True, timeout=10, input=b"{}"
    )


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data" / "statusline-ai-toolkit"


def assert_silent_success(result):
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def test_creates_the_data_dir_and_link(tmp_path, data):
    root = install(tmp_path, "1.0.0")
    assert_silent_success(run_hook(root, data))
    link = data / "statusline.py"
    assert link.is_symlink()
    assert os.readlink(link) == str(root / "scripts" / "statusline.py")
    assert sorted(p.name for p in data.iterdir()) == ["statusline.py"]


def test_is_idempotent(tmp_path, data):
    root = install(tmp_path, "1.0.0")
    run_hook(root, data)
    before = os.lstat(data / "statusline.py")
    assert_silent_success(run_hook(root, data))
    after = os.lstat(data / "statusline.py")
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_repoints_after_an_update(tmp_path, data):
    old = install(tmp_path, "1.0.0")
    new = install(tmp_path, "1.1.0")
    run_hook(old, data)
    assert_silent_success(run_hook(new, data))
    assert os.readlink(data / "statusline.py") == str(new / "scripts" / "statusline.py")
    assert sorted(p.name for p in data.iterdir()) == ["statusline.py"]


def test_repairs_a_dangling_link(tmp_path, data):
    old = install(tmp_path, "1.0.0")
    run_hook(old, data)
    shutil.rmtree(old)
    new = install(tmp_path, "1.1.0")
    assert_silent_success(run_hook(new, data))
    assert (data / "statusline.py").resolve() == (new / "scripts" / "statusline.py").resolve()


def test_replaces_a_stray_file(tmp_path, data):
    root = install(tmp_path, "1.0.0")
    data.mkdir(parents=True)
    (data / "statusline.py").write_text("old copy")
    assert_silent_success(run_hook(root, data))
    assert (data / "statusline.py").is_symlink()


@pytest.mark.parametrize("missing", ["root", "data"])
def test_does_nothing_without_plugin_env(tmp_path, data, missing):
    root = install(tmp_path, "1.0.0")
    result = run_hook(None if missing == "root" else root, None if missing == "data" else data)
    assert_silent_success(result)
    assert not data.exists()


def test_does_nothing_when_the_script_is_missing(tmp_path, data):
    root = tmp_path / "empty"
    root.mkdir()
    assert_silent_success(run_hook(root, data))
    assert not data.exists()


def test_fails_safe_when_the_data_dir_cannot_be_created(tmp_path):
    root = install(tmp_path, "1.0.0")
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert_silent_success(run_hook(root, blocker / "data"))


def test_linked_script_runs(tmp_path, data):
    root = install(tmp_path, "1.0.0")
    run_hook(root, data)
    result = subprocess.run(
        ["python3", str(data / "statusline.py")],
        input="{}",
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_STATUSLINE_THEME": "dark"},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 2


def test_shellcheck():
    shellcheck = shutil.which("shellcheck")
    if not shellcheck:
        pytest.skip("shellcheck not installed")
    scripts = sorted(str(p) for p in PLUGIN.rglob("*.sh"))
    assert scripts
    result = subprocess.run([shellcheck, *scripts], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
