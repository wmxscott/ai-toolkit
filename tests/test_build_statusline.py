import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "scripts" / "build_statusline.sh"
CHECKSUMS = ROOT / "plugins" / "statusline" / "checksums.txt"
NAMES = [
    "statusline-darwin-amd64",
    "statusline-darwin-arm64",
    "statusline-linux-amd64",
    "statusline-linux-arm64",
]

needs_go = pytest.mark.skipif(shutil.which("go") is None, reason="go not installed")


@pytest.fixture(scope="module")
def go_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("go")
    home = tmp / "home"
    home.mkdir()
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "GOCACHE": str(tmp / "cache"),
        "GOPATH": str(tmp / "gopath"),
    }


def build(env, *args):
    return subprocess.run(
        ["bash", str(BUILD), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


@needs_go
def test_check_matches_committed_checksums(go_env):
    result = build(go_env, "--check")
    assert result.returncode == 0, result.stdout + result.stderr


@needs_go
def test_writes_sorted_checksums_and_keeps_binaries(go_env, tmp_path):
    out = tmp_path / "dist"
    sums = tmp_path / "checksums.txt"
    result = build(go_env, "--out", str(out), "--checksums", str(sums))
    assert result.returncode == 0, result.stdout + result.stderr

    text = sums.read_text()
    assert text == CHECKSUMS.read_text()
    assert text.endswith("\n")
    lines = [line.split("  ") for line in text.splitlines()]
    assert [name for _, name in lines] == NAMES
    assert all(len(digest) == 64 for digest, _ in lines)
    assert sorted(p.name for p in out.iterdir()) == NAMES


@needs_go
def test_check_fails_on_a_different_checksum(go_env, tmp_path):
    sums = tmp_path / "checksums.txt"
    lines = CHECKSUMS.read_text().splitlines()
    lines[0] = "0" * 64 + lines[0][64:]
    sums.write_text("\n".join(lines) + "\n")

    result = build(go_env, "--check", "--checksums", str(sums))
    assert result.returncode == 1
    assert NAMES[0] in result.stdout + result.stderr
    assert sums.read_text() == "\n".join(lines) + "\n"


def test_fails_clearly_without_go(tmp_path):
    path = "/usr/bin:/bin"
    if shutil.which("go", path=path):
        pytest.skip("go is on the minimal PATH")
    result = build({"PATH": path, "HOME": str(tmp_path)}, "--check")
    assert result.returncode != 0
    assert "go" in result.stderr
