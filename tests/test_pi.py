"""Pi extensions and themes: the files `pi.extensions` and `pi.themes` list in package.json.

`schemas/pi-0.87.1-theme.schema.json` is Pi's theme schema (MIT) from
https://github.com/earendil-works/pi/blob/v0.87.1/packages/coding-agent/src/modes/interactive/theme/theme-schema.json
"""

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
PI_DIR = ROOT / "pi"
PACKAGE = json.loads((ROOT / "package.json").read_text())
EXTENSIONS = PACKAGE["pi"]["extensions"]
THEMES = PACKAGE["pi"]["themes"]
THEME_SCHEMA = json.loads((ROOT / "tests" / "schemas" / "pi-0.87.1-theme.schema.json").read_text())
README = (ROOT / "README.md").read_text()
PI_README = (PI_DIR / "README.md").read_text()

# Pi supplies these to extensions; the package has no dependencies of its own.
PI_SUPPLIED = {
    "@earendil-works/pi-ai",
    "@earendil-works/pi-agent-core",
    "@earendil-works/pi-coding-agent",
    "@earendil-works/pi-tui",
    "typebox",
}
TRIGGER = ".local/share/theme-monitor/theme-change.trigger"


def listed(entries, directory, suffix):
    paths = []
    for entry in entries:
        assert entry.startswith(f"./pi/{directory}/"), entry
        assert entry.endswith(suffix), entry
        paths.append(ROOT / entry)
    return paths


EXTENSION_FILES = listed(EXTENSIONS, "extensions", ".ts")
THEME_FILES = listed(THEMES, "themes", ".json")


def test_package_lists_every_extension_and_theme_once():
    assert sorted(EXTENSION_FILES) == sorted((PI_DIR / "extensions").iterdir())
    assert sorted(THEME_FILES) == sorted((PI_DIR / "themes").iterdir())
    assert len(set(EXTENSIONS)) == len(EXTENSIONS)
    assert len(set(THEMES)) == len(THEMES)
    assert all(path.is_file() for path in EXTENSION_FILES + THEME_FILES)


@pytest.mark.parametrize("path", THEME_FILES, ids=lambda p: p.name)
def test_theme_matches_pi_schema(path):
    theme = json.loads(path.read_text())
    jsonschema.validate(theme, THEME_SCHEMA)
    assert theme["name"] == path.stem
    for value in theme["colors"].values():
        if isinstance(value, str) and value and not value.startswith("#"):
            assert value in theme["vars"], value


def test_themes_define_the_same_colours():
    keys = [set(json.loads(path.read_text())["colors"]) for path in THEME_FILES]
    assert all(k == keys[0] for k in keys)


def test_theme_switcher_names_packaged_themes():
    source = (PI_DIR / "extensions" / "theme-switcher.ts").read_text()
    names = set(re.findall(r'(?:dark|light): "([a-z0-9-]+)"', source))
    assert names == {path.stem for path in THEME_FILES}


@pytest.mark.parametrize("path", EXTENSION_FILES, ids=lambda p: p.name)
def test_extension_imports_only_what_pi_supplies(path):
    source = path.read_text()
    specifiers = re.findall(r'^\s*(?:import|export)\b[^;]*?\bfrom\s+"([^"]+)"', source, re.M | re.S)
    assert specifiers
    for spec in specifiers:
        assert spec.startswith("node:") or spec in PI_SUPPLIED, spec
    assert re.search(r"^export default function\b", source, re.M)


@pytest.mark.parametrize(
    "path",
    sorted(p for p in PI_DIR.rglob("*") if p.suffix in {".ts", ".json", ".md"}),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_no_personal_paths(path):
    text = path.read_text()
    assert not re.search(r"/(?:Users|home)/(?!linuxbrew/)[^/\s\"']+", text)
    assert "dotfiles" not in text.lower()


def test_theme_monitor_trigger_is_its_public_default():
    for name in ("statusline.ts", "theme-switcher.ts"):
        source = (PI_DIR / "extensions" / name).read_text()
        assert TRIGGER in source and "homedir()" in source


def test_display_keeps_pix_display_attribution_and_licence():
    source = (PI_DIR / "extensions" / "display.ts").read_text()
    for text in (
        "Adapted from pix-display by xynogen",
        "https://github.com/xynogen/pix-mono/tree/main/packages/pix-display",
        "MIT License",
        "Copyright (c) 2026 xynogen",
        "The above copyright notice and this permission notice shall be included in all",
        'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND',
    ):
        assert text in source, text
    assert "pix-display" in PI_README and "xynogen" in PI_README


def test_readmes_cover_every_extension_and_the_filter():
    for path in EXTENSION_FILES:
        assert f"`{path.name}`" in PI_README, path.name
    assert "theme-monitor" in PI_README
    assert "brew install wmxscott/tap/theme-monitor" in PI_README
    assert "## Pi extensions" in README
    assert '"source": "git:github.com/wmxscott/ai-toolkit"' in README
    assert '"skills": []' in README


STRIP_TYPES = (
    'import { stripTypeScriptTypes } from "node:module";'
    'import { readFileSync } from "node:fs";'
    'process.stdout.write(stripTypeScriptTypes(readFileSync(process.argv[1], "utf8")));'
)


def strip_types(path):
    """Node's own TypeScript parser (22.13 and later) turns `path` into plain JavaScript,
    and throws on a syntax error. `node --check` alone passes a broken .ts module."""
    return subprocess.run(
        ["node", "--no-warnings", "--input-type=module", "-e", STRIP_TYPES, str(path)],
        capture_output=True,
        text=True,
    )


def node_strips_types():
    if not shutil.which("node"):
        return False
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory) / "probe.ts"
        probe.write_text("const x: number = 1;\n")
        return strip_types(probe).stdout.startswith("const x")


@pytest.mark.skipif(not node_strips_types(), reason="needs node 22.13 or later")
@pytest.mark.parametrize("path", EXTENSION_FILES, ids=lambda p: p.name)
def test_extension_parses(path, tmp_path):
    stripped = strip_types(path)
    assert stripped.returncode == 0, stripped.stderr
    module = tmp_path / f"{path.stem}.mjs"
    module.write_text(stripped.stdout)
    checked = subprocess.run(["node", "--check", str(module)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


def test_syntax_check_catches_a_broken_extension(tmp_path):
    if not node_strips_types():
        pytest.skip("needs node 22.13 or later")
    broken = tmp_path / "broken.ts"
    broken.write_text('import { a } from "node:fs";\nconst y: { x: number } = { x: 1 ;\n')
    assert strip_types(broken).returncode != 0


def run_pi(tmp_path, package):
    """Load the package with Pi's own loader in a throwaway home, and list its commands."""
    home = tmp_path / "home"
    agent = home / ".pi" / "agent"
    agent.mkdir(parents=True)
    (agent / "settings.json").write_text(json.dumps({"packages": [package]}))
    (home / "gitconfig").touch()
    work = tmp_path / "work"
    work.mkdir()
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "TERM": "dumb",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PI_CODING_AGENT_DIR": str(agent),
        "PI_CODING_AGENT_SESSION_DIR": str(home / "sessions"),
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
    }
    if subprocess.run(["pi", "--version"], capture_output=True, env=env).returncode != 0:
        pytest.skip("pi does not run in an isolated home")
    done = subprocess.run(
        ["pi", "--mode", "rpc", "--no-session"],
        input='{"id":"1","type":"get_commands"}\n',
        capture_output=True,
        text=True,
        cwd=work,
        env=env,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    response = next(
        record
        for record in map(json.loads, done.stdout.splitlines())
        if record.get("command") == "get_commands"
    )
    assert response["success"], response
    return {
        command["name"]: command["sourceInfo"]["path"]
        for command in response["data"]["commands"]
        if command["sourceInfo"].get("origin") == "package"
    }


needs_pi = pytest.mark.skipif(not shutil.which("pi"), reason="needs the pi CLI")


@needs_pi
def test_pi_loads_the_whole_package(tmp_path):
    commands = run_pi(tmp_path, str(ROOT))
    assert commands["statusline"] == str(PI_DIR / "extensions" / "statusline.ts")
    assert any(name.startswith("skill:") for name in commands)


@needs_pi
def test_pi_filter_drops_the_skills(tmp_path):
    commands = run_pi(tmp_path, {"source": str(ROOT), "skills": []})
    assert set(commands) == {"statusline"}


# pr-tracker.ts: Pi's side of plugins/pr-tracker. Its tests stub the CLI and build every
# environment from scratch, so neither a real pr-tracker nor its ledger is ever reached.
PR_TRACKER = PI_DIR / "extensions" / "pr-tracker.ts"
PR_TRACKER_STUB = """#!/bin/bash
n=$(ls "$STUB_OUT" | grep -c '[.]json$')
printf '%s\\n' "$@" > "$STUB_OUT/$n.args"
cat > "$STUB_OUT/$n.json"
printf 'stub noise\\n' >&2
event='"PR #7: checks failing"'
case "$STUB_MODE:$2" in
  ok:post-bash) printf '{"hookSpecificOutput":{"additionalContext":%s}}\\n' "$event" ;;
  ok:stop) printf '{"systemMessage":%s}\\n' "$event" ;;
  broken:*) printf 'Traceback\\n'; exit 1 ;;
esac
"""


def test_package_carries_pr_trackers_extension_and_skills():
    assert "./pi/extensions/pr-tracker.ts" in EXTENSIONS
    assert "./plugins/pr-tracker/skills" in PACKAGE["pi"]["skills"]
    assert '"skills": ["plugins/pr-tracker/skills/*"]' in README
    assert "`pr-tracker.ts`" in PI_README


def tool_dir(name):
    """The real directory of a tool, so a PATH entry for it can't bring along a real
    pr-tracker installed next to a symlink, as in Homebrew's bin."""
    return str(Path(os.path.realpath(shutil.which(name))).parent)


class PrTrackerSandbox:
    def __init__(self, root: Path, *tools: str):
        self.root = root
        self.home = root / "home"
        self.bin = root / "bin"
        self.out = root / "out"
        self.work = root / "work"
        for directory in (self.home, self.bin, self.out, self.work):
            directory.mkdir()
        (self.home / "gitconfig").touch()
        path = os.pathsep.join([str(self.bin), *map(tool_dir, tools), "/usr/bin", "/bin"])
        assert not shutil.which("pr-tracker", path=path), "a real pr-tracker would leak in"
        self.env = {
            "HOME": str(self.home),
            "PATH": path,
            "TERM": "dumb",
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            "GIT_CONFIG_GLOBAL": str(self.home / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "PR_TRACKER_STATE_DIR": str(root / "state"),
            "PR_TRACKER_HOOK_FALLBACK_PATH": "",
            "STUB_OUT": str(self.out),
            "STUB_MODE": "ok",
        }

    def stub(self, mode="ok"):
        path = self.bin / "pr-tracker"
        path.write_text(PR_TRACKER_STUB)
        path.chmod(0o755)
        self.env["STUB_MODE"] = mode

    def calls(self):
        return [
            (
                (self.out / f"{n}.args").read_text().split(),
                json.loads((self.out / f"{n}.json").read_text()),
            )
            for n in range(len(list(self.out.glob("*.json"))))
        ]


HARNESS = """
const { default: extension } = await import(process.argv[1]);
const handlers = {};
extension({ on: (name, handler) => { handlers[name] = handler; } });
const notes = [];
const ctx = {
  cwd: "/work",
  sessionManager: { getSessionId: () => "pi-session" },
  ui: { notify: (message, level) => notes.push([message, level]) },
};
const result = (toolName, command) => ({
  type: "tool_result", toolName, toolCallId: "call-1", input: { command },
  content: [{ type: "text", text: "https://github.com/owner/repo/pull/7\\n" }],
  isError: false, details: undefined,
});
await handlers.session_start({ type: "session_start", reason: "startup" }, ctx);
const bash = await handlers.tool_result(result("bash", "gh pr create --fill"), ctx);
const read = await handlers.tool_result(result("read", undefined), ctx);
await handlers.agent_settled({ type: "agent_settled" }, ctx);
console.log(JSON.stringify({ bash: bash ?? null, read: read ?? null, notes }));
"""


def run_harness(sandbox):
    """Load pr-tracker.ts in node against a fake Pi event API, and fire one bash result,
    one other tool's result and the end of a run."""
    stripped = strip_types(PR_TRACKER)
    assert stripped.returncode == 0, stripped.stderr
    module = sandbox.root / "pr-tracker.mjs"
    module.write_text(stripped.stdout)
    done = subprocess.run(
        ["node", "--input-type=module", "-e", HARNESS, str(module)],
        capture_output=True,
        text=True,
        env=sandbox.env,
        cwd=sandbox.work,
        timeout=30,
    )
    assert (done.returncode, done.stderr) == (0, "")
    return json.loads(done.stdout)


needs_strip_types = pytest.mark.skipif(not node_strips_types(), reason="needs node 22.13 or later")


@needs_strip_types
def test_pr_tracker_appends_events_to_a_bash_result(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub()
    result = run_harness(sandbox)
    assert result["bash"] == {
        "content": [
            {"type": "text", "text": "https://github.com/owner/repo/pull/7\n"},
            {"type": "text", "text": "\n\nPR #7: checks failing"},
        ]
    }
    assert result["read"] is None
    assert result["notes"] == [["PR #7: checks failing", "info"]]
    base = {"session_id": "pi-session", "cwd": "/work"}
    assert sandbox.calls() == [
        (
            ["hook", "post-bash", "--agent", "pi"],
            {
                **base,
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "gh pr create --fill"},
                "tool_response": "https://github.com/owner/repo/pull/7\n",
            },
        ),
        (["hook", "stop", "--agent", "pi"], {**base, "hook_event_name": "Stop"}),
    ]


@needs_strip_types
def test_pr_tracker_without_the_cli_does_nothing(tmp_path):
    result = run_harness(PrTrackerSandbox(tmp_path, "node"))
    assert result == {"bash": None, "read": None, "notes": []}


@needs_strip_types
def test_pr_tracker_ignores_a_broken_cli(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub("broken")
    assert run_harness(sandbox) == {"bash": None, "read": None, "notes": []}
    assert len(sandbox.calls()) == 2


@needs_strip_types
def test_pr_tracker_finds_the_cli_in_the_fallback_dirs(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub()
    fallback = tmp_path / "fallback"
    (sandbox.bin / "pr-tracker").rename(fallback.mkdir() or fallback / "pr-tracker")
    sandbox.env["PR_TRACKER_HOOK_FALLBACK_PATH"] = str(fallback)
    assert run_harness(sandbox)["notes"] == [["PR #7: checks failing", "info"]]


# A test-only extension: Pi's faux provider stands in for a model and asks for one bash call.
FAUX_MODEL = """
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
\tconst faux = fauxProvider();
\tfaux.setResponses([
\t\tfauxAssistantMessage(fauxToolCall("bash", { command: process.env.FAUX_COMMAND })),
\t\tfauxAssistantMessage("done"),
\t]);
\tpi.registerProvider(faux.provider);
}
"""


FAUX_FLAGS = ("--provider", "faux", "--model", "faux-1")


def run_pi_turn(sandbox):
    """One real Pi run in RPC mode, with the package installed in a throwaway home and a
    faux model that runs one bash command. Returns Pi's output records."""
    agent = sandbox.home / ".pi" / "agent"
    agent.mkdir(parents=True)
    (agent / "settings.json").write_text(json.dumps({"packages": [str(ROOT)]}))
    faux = sandbox.root / "faux.ts"
    faux.write_text(FAUX_MODEL)
    env = {
        **sandbox.env,
        "PI_CODING_AGENT_DIR": str(agent),
        "PI_CODING_AGENT_SESSION_DIR": str(sandbox.home / "sessions"),
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
        "FAUX_COMMAND": "echo https://github.com/owner/repo/pull/7; echo $PI_SESSION_ID",
    }
    pi = subprocess.Popen(
        ["pi", "--mode", "rpc", "--no-session", "-e", str(faux), *FAUX_FLAGS],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=sandbox.work,
        env=env,
    )
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in pi.stdout], daemon=True).start()
    done = "extension_ui_request" if (sandbox.bin / "pr-tracker").exists() else "agent_end"
    records = []
    try:
        pi.stdin.write('{"id":"1","type":"prompt","message":"go"}\n')
        pi.stdin.flush()
        deadline = time.monotonic() + 60
        while not records or records[-1].get("type") != done:
            records.append(json.loads(lines.get(timeout=max(deadline - time.monotonic(), 0))))
    finally:
        pi.stdin.close()
        try:
            pi.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pi.kill()
    assert pi.stderr.read() == ""
    return records


def tool_results(records):
    return [
        record["message"]["content"]
        for record in records
        if record.get("type") == "message_end" and record["message"]["role"] == "toolResult"
    ]


@needs_pi
def test_pi_runs_pr_tracker_on_a_real_bash_call(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "pi", "node")
    sandbox.stub()
    records = run_pi_turn(sandbox)
    [(args, post), (stop_args, stop)] = sandbox.calls()
    session = post["session_id"]
    assert session and stop["session_id"] == session
    assert (args, stop_args) == (
        ["hook", "post-bash", "--agent", "pi"],
        ["hook", "stop", "--agent", "pi"],
    )
    output = f"https://github.com/owner/repo/pull/7\n{session}\n"
    assert post["tool_response"] == output, "PI_SESSION_ID is the session the hook reports"
    assert tool_results(records) == [
        [{"type": "text", "text": output}, {"type": "text", "text": "\n\nPR #7: checks failing"}]
    ]
    [note] = [r for r in records if r.get("type") == "extension_ui_request"]
    assert (note["method"], note["message"]) == ("notify", "PR #7: checks failing")


@needs_pi
def test_pi_without_the_cli_leaves_the_bash_result_alone(tmp_path):
    records = run_pi_turn(PrTrackerSandbox(tmp_path, "pi", "node"))
    [[content]] = tool_results(records)
    assert content["text"].startswith("https://github.com/owner/repo/pull/7\n")
    assert not [r for r in records if r.get("type") == "extension_ui_request"]


@needs_pi
def test_pi_filter_keeps_only_pr_trackers_skills(tmp_path):
    commands = run_pi(tmp_path, {"source": str(ROOT), "skills": ["plugins/pr-tracker/skills/*"]})
    assert {name for name in commands if name.startswith("skill:")} == {
        "skill:pr-tracker",
        "skill:prs",
    }
    assert "statusline" in commands
