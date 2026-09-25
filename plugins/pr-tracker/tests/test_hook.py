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


def cli_args(command: str) -> list[str]:
    return command.split('hook.sh"', 1)[1].split()


WAIT = next(command for command in hook_commands() if cli_args(command)[:1] == ["wait"])
BLOCKING = [command for command in hook_commands() if command != WAIT]


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
    assert sandbox.calls() == ["stub", "hook", *cli_args(command)]
    assert sandbox.stdin_seen() == PAYLOAD


@pytest.mark.parametrize("status", [1, 2, 127])
@pytest.mark.parametrize("command", BLOCKING)
def test_a_failing_cli_never_reaches_the_session(sandbox, command, status):
    sandbox.stub(sandbox.bin)
    sandbox.env["STUB_STATUS"] = str(status)
    result = sandbox.run(command)
    assert (result.returncode, result.stderr) == (0, b"")
    assert sandbox.calls() is not None


@pytest.mark.parametrize(("status", "expected"), [(0, 0), (1, 0), (2, 2), (127, 0)])
def test_only_wait_passes_its_wake_status_through(sandbox, status, expected):
    """asyncRewake wakes the session on exit 2, with what `wait` printed."""
    sandbox.stub(sandbox.bin)
    sandbox.env["STUB_STATUS"] = str(status)
    sandbox.env["STUB_STDOUT"] = "Tracked pull request updates:"
    result = sandbox.run(WAIT)
    assert (result.returncode, result.stdout, result.stderr) == (
        expected,
        b"Tracked pull request updates:",
        b"",
    )


def test_finds_the_cli_off_a_minimal_path(sandbox):
    sandbox.stub(sandbox.fallback)
    sandbox.env["PATH"] = SYSTEM_PATH
    result = sandbox.run(hook_commands()[0])
    assert result.returncode == 0
    assert sandbox.calls() == ["stub", "hook"]


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


CODEX_PAYLOAD = json.dumps(
    {
        "session_id": "019a0000-0000-7000-8000-000000000000",
        "turn_id": "019a0000-0000-7000-8000-000000000001",
        "transcript_path": None,
        "cwd": "/tmp/project",
        "hook_event_name": "PostToolUse",
        "model": "gpt-5.5",
        "permission_mode": "default",
        "tool_name": "Bash",
        "tool_use_id": "call-1",
        "tool_input": {"command": "gh pr create --fill"},
        "tool_response": "https://github.com/owner/repo/pull/7\n",
    }
).encode()


def test_codex_payload_reaches_the_cli_unchanged(sandbox):
    """Codex sets CLAUDE_PLUGIN_ROOT for plugin hooks and sends a Claude-shaped payload with
    Codex's own keys, such as `turn_id`. Nothing else from Claude Code is in its environment."""
    assert not [
        key for key in sandbox.env if key.startswith("CLAUDE_") and key != "CLAUDE_PLUGIN_ROOT"
    ]
    sandbox.stub(sandbox.bin)
    context = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "x"}}
    sandbox.env["STUB_STDOUT"] = json.dumps(context)
    result = sandbox.run(hook_commands()[0], CODEX_PAYLOAD)
    assert (result.returncode, result.stderr) == (0, b"")
    assert json.loads(result.stdout) == context
    assert sandbox.calls() == ["stub", "hook"]
    assert sandbox.stdin_seen() == CODEX_PAYLOAD


def test_runs_without_home_or_the_plugin_root(sandbox):
    sandbox.stub(sandbox.fallback)
    for key in ("HOME", "CLAUDE_PLUGIN_ROOT"):
        del sandbox.env[key]
    sandbox.env["PATH"] = SYSTEM_PATH
    result = sandbox.run(f'bash "{PLUGIN}/scripts/hook.sh" stop', CODEX_PAYLOAD)
    assert (result.returncode, result.stderr) == (0, b"")
    assert sandbox.calls() == ["stub", "hook", "stop"]
