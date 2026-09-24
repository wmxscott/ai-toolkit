"""Drives scripts/hook.sh through the commands in hooks.json, with a stub pr-tracker and an
environment built from scratch, so no real CLI, ledger or $HOME is ever reached."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
SYSTEM_PATH = "/usr/bin:/bin"
PAYLOAD = json.dumps(
    {
        "session_id": "test-session",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create --fill"},
        "tool_response": {"stdout": "x" * 200_000},
    }
).encode()

STUB = """#!/bin/bash
printf '%s\\n' "$STUB_NAME" "$@" > "$STUB_DIR/args"
cat > "$STUB_DIR/stdin"
printf '%s' "$STUB_STDOUT"
printf 'stub noise\\n' >&2
exit "${STUB_STATUS:-0}"
"""


def hook_commands():
    return [
        hook["command"] for groups in HOOKS.values() for group in groups for hook in group["hooks"]
    ]


class Sandbox:
    def __init__(self, root: Path):
        assert not shutil.which("pr-tracker", path=SYSTEM_PATH), "it would leak into the tests"
        self.root = root
        self.home = root / "home"
        self.bin = root / "bin"
        self.fallback = root / "fallback"
        for directory in (self.home, self.bin, self.fallback):
            directory.mkdir()
        self.env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "PR_TRACKER_STATE_DIR": str(root / "state"),
            "PATH": f"{self.bin}:{SYSTEM_PATH}",
            "PR_TRACKER_HOOK_FALLBACK_PATH": str(self.fallback),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
            "STUB_DIR": str(root),
            "STUB_STDOUT": "",
        }

    def stub(self, directory: Path, name: str = "stub") -> None:
        path = directory / "pr-tracker"
        path.write_text(STUB.replace("$STUB_NAME", name))
        path.chmod(0o755)

    def run(self, command: str, stdin: bytes = PAYLOAD) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/sh", "-c", command],
            input=stdin,
            env=self.env,
            capture_output=True,
            timeout=10,
        )

    def calls(self) -> list[str] | None:
        args = self.root / "args"
        return args.read_text().splitlines() if args.exists() else None

    def stdin_seen(self) -> bytes:
        return (self.root / "stdin").read_bytes()


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


@pytest.mark.parametrize("command", hook_commands())
def test_without_the_cli_does_nothing(sandbox, command):
    result = sandbox.run(command)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


@pytest.mark.parametrize("command", hook_commands())
def test_runs_the_cli_with_the_mode_and_payload(sandbox, command):
    sandbox.stub(sandbox.bin)
    sandbox.env["STUB_STDOUT"] = '{"systemMessage": "PR #1: checks failing"}'
    result = sandbox.run(command)
    assert result.returncode == 0
    assert result.stdout == b'{"systemMessage": "PR #1: checks failing"}'
    assert result.stderr == b""
    assert sandbox.calls() == ["stub", "hook", command.rsplit(" ", 1)[1]]
    assert sandbox.stdin_seen() == PAYLOAD


@pytest.mark.parametrize("status", [1, 2, 127])
def test_a_failing_cli_never_reaches_the_session(sandbox, status):
    sandbox.stub(sandbox.bin)
    sandbox.env["STUB_STATUS"] = str(status)
    result = sandbox.run(hook_commands()[-1])
    assert (result.returncode, result.stderr) == (0, b"")
    assert sandbox.calls() is not None


def test_finds_the_cli_off_a_minimal_path(sandbox):
    sandbox.stub(sandbox.fallback)
    sandbox.env["PATH"] = SYSTEM_PATH
    result = sandbox.run(hook_commands()[0])
    assert result.returncode == 0
    assert sandbox.calls() == ["stub", "hook", "post-bash"]


def test_path_wins_over_the_fallback(sandbox):
    sandbox.stub(sandbox.bin, "on-path")
    sandbox.stub(sandbox.fallback, "fallback")
    sandbox.run(hook_commands()[0])
    assert sandbox.calls()[0] == "on-path"


def test_default_fallback_is_homebrew_then_user_installs(sandbox):
    (sandbox.bin / "pr-tracker").write_text('#!/bin/bash\nprintf %s "$PATH"\n')
    (sandbox.bin / "pr-tracker").chmod(0o755)
    del sandbox.env["PR_TRACKER_HOOK_FALLBACK_PATH"]
    result = sandbox.run(hook_commands()[0])
    assert result.stdout.decode().split(":") == [
        str(sandbox.bin),
        *SYSTEM_PATH.split(":"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/home/linuxbrew/.linuxbrew/bin",
        str(sandbox.home / ".local" / "bin"),
    ]


def test_empty_fallback_leaves_path_alone(sandbox):
    (sandbox.bin / "pr-tracker").write_text('#!/bin/bash\nprintf %s "$PATH"\n')
    (sandbox.bin / "pr-tracker").chmod(0o755)
    sandbox.env["PR_TRACKER_HOOK_FALLBACK_PATH"] = ""
    result = sandbox.run(hook_commands()[0])
    assert result.stdout.decode() == sandbox.env["PATH"]
