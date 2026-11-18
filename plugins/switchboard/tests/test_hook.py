"""Drives scripts/hook.sh through the commands in hooks.json, with a stub switchboard and an
environment built from scratch, so no real CLI, tmux server or $HOME is ever reached."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
HOOKS = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
SYSTEM_PATH = "/usr/bin:/bin"

STUB = """#!/bin/bash
printf '%s\\n' "$@" > "$STUB_DIR/args"
cat > "$STUB_DIR/stdin"
"""

COMMANDS = {
    event: hook["command"]
    for event, groups in HOOKS.items()
    for group in groups
    for hook in group["hooks"]
}


def payload(event: str) -> bytes:
    return json.dumps(
        {
            "session_id": "test-session",
            "hook_event_name": event,
            "tool_name": "AskUserQuestion",
            "tool_response": {"stdout": "x" * 200_000},
        }
    ).encode()


class Sandbox:
    def __init__(self, root: Path):
        assert not shutil.which("switchboard", path=SYSTEM_PATH), "it would leak into the tests"
        self.root = root
        self.home = root / "home"
        self.bin = root / "bin"
        for directory in (self.home, self.bin):
            directory.mkdir()
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{SYSTEM_PATH}",
            "TMUX_PANE": "%7",
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN),
            "STUB_DIR": str(root),
        }

    def stub(self) -> None:
        path = self.bin / "switchboard"
        path.write_text(STUB)
        path.chmod(0o755)

    def run(self, command: str, stdin: bytes) -> subprocess.CompletedProcess:
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


@pytest.mark.parametrize("event", COMMANDS)
def test_hands_the_event_and_payload_to_the_cli(sandbox, event):
    sandbox.stub()
    result = sandbox.run(COMMANDS[event], payload(event))
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
    assert sandbox.calls() == ["hook", event]
    assert sandbox.stdin_seen() == payload(event)


@pytest.mark.parametrize("pane", [None, ""])
@pytest.mark.parametrize("event", COMMANDS)
def test_outside_tmux_never_starts_the_cli(sandbox, event, pane):
    sandbox.stub()
    if pane is None:
        del sandbox.env["TMUX_PANE"]
    else:
        sandbox.env["TMUX_PANE"] = pane
    result = sandbox.run(COMMANDS[event], payload(event))
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
    assert sandbox.calls() is None


@pytest.mark.parametrize("event", COMMANDS)
def test_without_the_cli_does_nothing(sandbox, event):
    result = sandbox.run(COMMANDS[event], payload(event))
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
