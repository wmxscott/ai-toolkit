import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN / "scripts"

# Logs each call as tab-separated argv, so tests can assert exact arguments.
STUB = """#!/bin/bash
{ printf '%s' "$(basename "$0")"; printf '\\t%s' "$@"; printf '\\n'; } >> "$STUB_LOG"
"""

HERDR_STUB = (
    STUB
    + """if [ "$1 $2" = "tab get" ]; then
    printf '{"result":{"tab":{"pane_count":%s}}}\\n' "${STUB_PANE_COUNT:-1}"
fi
"""
)


class Sandbox:
    """A scratch $HOME and a PATH holding only jq, the stubs asked for, and the system dirs."""

    def __init__(self, root: Path):
        self.home = root / "home"
        self.bin = root / "bin"
        self.log = root / "calls.log"
        self.tty = root / "tty"
        self.home.mkdir()
        self.bin.mkdir()
        jq = shutil.which("jq")
        assert jq, "tests need jq"
        (self.bin / "jq").symlink_to(jq)
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "STUB_LOG": str(self.log),
            "TERMINAL_TITLE_TTY": str(self.tty),
        }
        self.tty.touch()

    def stub(self, name: str) -> None:
        path = self.bin / name
        path.write_text(HERDR_STUB if name == "herdr" else STUB)
        path.chmod(0o755)

    def herdr(self, tab="tab-1", pane="pane-1", panes=1) -> None:
        self.stub("herdr")
        self.env.update(HERDR_TAB_ID=tab, HERDR_PANE_ID=pane, STUB_PANE_COUNT=str(panes))

    def tmux(self, pane="%3") -> None:
        self.stub("tmux")
        self.env.update(TMUX="/tmp/tmux-test/default,1,0", TMUX_PANE=pane)

    def run(self, script, *args, stdin=None, script_dir=SCRIPTS, new_session=False):
        if isinstance(stdin, dict):
            stdin = json.dumps(stdin)
        return subprocess.run(
            ["bash", str(script_dir / script), *args],
            input=(stdin or "").encode(),
            env=self.env,
            capture_output=True,
            check=True,
            timeout=10,
            start_new_session=new_session,
        )

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [line.split("\t") for line in self.log.read_text().splitlines()]

    def clear_calls(self) -> None:
        self.log.unlink(missing_ok=True)

    @staticmethod
    def osc(title: str) -> bytes:
        return b"\x1b]0;" + title.encode() + b"\x07"

    def written(self) -> bytes:
        return self.tty.read_bytes()

    def cached(self, session_id: str) -> Path:
        return self.home / ".cache" / "claude-terminal-title" / session_id


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)
