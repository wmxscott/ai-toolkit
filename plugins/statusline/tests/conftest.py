import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
PLUGIN = SCRIPTS.parent
PLATFORMS = [(o, a) for o in ("darwin", "linux") for a in ("arm64", "amd64")]
HOOK_TOOLS = (
    "awk", "bash", "cat", "chmod", "cp", "find", "grep", "head", "ln",
    "mkdir", "mktemp", "mv", "readlink", "rm", "rmdir", "sed", "sleep",
)  # fmt: skip
SHA256 = (
    "import hashlib, sys; p = sys.argv[-1]; "
    'print(hashlib.sha256(open(p, "rb").read()).hexdigest() + "  " + p)'
)


class Release:
    """A plugin install at `version` and a fake GitHub release of its binaries.

    `tools` holds the only commands on PATH: the real basics plus stubs for
    uname, curl (served from `serve`, logged to `curl_log`) and shasum.
    """

    def __init__(self, base: Path, version: str = "2.0.0"):
        self.base = base
        self.tools = base / "tools"
        self.serve = base / "serve"
        self.curl_log = base / "curl.log"
        self.tools.mkdir(parents=True, exist_ok=True)
        for name in HOOK_TOOLS:
            real = shutil.which(name, path="/usr/bin:/bin")
            if real and not (self.tools / name).exists():
                (self.tools / name).symlink_to(real)
        self.uname("Darwin", "arm64")
        self.curl()
        self.sha("shasum")
        self.publish(version)

    def publish(self, version: str):
        """Install the plugin at `version` and publish its release; returns the root."""
        self.version = version
        self.root = self.base / "cache" / version
        shutil.copytree(SCRIPTS, self.root / "scripts")
        manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        manifest["version"] = version
        (self.root / ".claude-plugin").mkdir()
        (self.root / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2))
        sums = []
        for os_, arch in PLATFORMS:
            name = f"statusline-{os_}-{arch}"
            path = self.serve / f"statusline-v{version}" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.binary(os_, arch, version))
            sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}\n")
        (self.root / "checksums.txt").write_text("".join(sums))
        return self.root

    @staticmethod
    def binary(os_, arch, version):
        return f"#!/bin/sh\ncat >/dev/null\necho 'statusline {version} {os_}-{arch}'\n".encode()

    def stub(self, name, body):
        path = self.tools / name
        if path.is_symlink() or path.exists():
            path.unlink()
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def uname(self, system, machine):
        self.stub("uname", f'case "$1" in -s) echo {system} ;; -m) echo {machine} ;; esac\n')

    def curl(self, delay=0):
        self.stub(
            "curl",
            f"""printf '%s\\n' "$*" >> '{self.curl_log}'
out= url=
while [ $# -gt 0 ]; do
    case "$1" in -o) out=$2; shift ;; -*) ;; *) url=$1 ;; esac
    shift
done
sleep {delay}
src='{self.serve}'/"${{url#https://github.com/wmxscott/ai-toolkit/releases/download/}}"
[ -f "$src" ] || exit 22
cp "$src" "$out"
""",
        )

    def sha(self, name):
        self.stub(name, f"exec '{sys.executable}' -c '{SHA256}' \"$@\"\n")

    def remove(self, *names):
        for name in names:
            (self.tools / name).unlink(missing_ok=True)

    def curl_calls(self):
        return self.curl_log.read_text().splitlines() if self.curl_log.exists() else []

    def env(self, data=None, **extra):
        env = {"PATH": str(self.tools), "CLAUDE_PLUGIN_ROOT": str(self.root), **extra}
        if data is not None:
            env["CLAUDE_PLUGIN_DATA"] = str(data)
        return env


@pytest.fixture
def release(tmp_path):
    return Release(tmp_path / "release")
