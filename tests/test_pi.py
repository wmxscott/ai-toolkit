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
# ok: every hook has news, which Stop only shows. wake: only the STUB_WAKE_ON'th Stop call
# has news, and hands it to the agent.
PR_TRACKER_STUB = """#!/bin/bash
n=$(ls "$STUB_OUT" | grep -c '[.]json$')
printf '%s\\n' "$@" > "$STUB_OUT/$n.args"
cat > "$STUB_OUT/$n.json"
printf 'stub noise\\n' >&2
event=$(grep -o '"hook_event_name":"[A-Za-z]*"' "$STUB_OUT/$n.json" | cut -d'"' -f4)
stops=$(grep -l '"hook_event_name":"Stop"' "$STUB_OUT"/*.json | wc -l | tr -d ' ')
news='"PR #7: checks failing"'
context='{"hookSpecificOutput":{"additionalContext":%s}}\\n'
case "$STUB_MODE:$event" in
  ok:Stop) printf '{"systemMessage":%s}\\n' "$news" ;;
  ok:*) printf "$context" "$news" ;;
  wake:Stop) if [ "$stops" = "$STUB_WAKE_ON" ]; then printf "$context" "$news"; fi ;;
  broken:*) printf 'Traceback\\n'; exit 1 ;;
esac
"""
NEWS = "PR #7: checks failing"
MESSAGE = {"customType": "pr-tracker", "content": NEWS, "display": True}
AS_PI = ["hook", "--agent", "pi"]
STOP = ["hook", "stop", "--agent", "pi"]


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

    def stub(self, mode="ok", wake_on=0):
        path = self.bin / "pr-tracker"
        path.write_text(PR_TRACKER_STUB)
        path.chmod(0o755)
        self.env["STUB_MODE"] = mode
        self.env["STUB_WAKE_ON"] = str(wake_on)

    def calls(self):
        return [
            (
                (self.out / f"{n}.args").read_text().split(),
                json.loads((self.out / f"{n}.json").read_text()),
            )
            for n in range(len(list(self.out.glob("*.json"))))
        ]


# A fake Pi event API. Timers are recorded, not run: the harness runs the first by hand.
HARNESS = """
const { default: extension } = await import(process.argv[1]);
const timers = new Map();
const delays = [];
let ids = 0;
globalThis.setTimeout = (tick, ms) => {
  timers.set(++ids, tick);
  delays.push(ms);
  return { id: ids, unref() {} };
};
globalThis.clearTimeout = (timer) => timer && timers.delete(timer.id);
const handlers = {};
const sent = [];
const notes = [];
extension({
  on: (name, handler) => { handlers[name] = handler; },
  sendMessage: (message, options) => sent.push([message, options]),
});
const ctx = {
  mode: process.env.HARNESS_MODE,
  cwd: "/work",
  sessionManager: { getSessionId: () => "pi-session" },
  ui: { notify: (message, level) => notes.push([message, level]) },
};
const fire = async (type, event = {}) => (await handlers[type]({ type, ...event }, ctx)) ?? null;
const result = (toolName, input, isError = false) => ({
  toolName, toolCallId: "call-1", input, isError, details: undefined,
  content: [{ type: "text", text: "https://github.com/owner/repo/pull/7\\n" }],
});
const settle = { outcome: process.env.HARNESS_OUTCOME, entries: [], continue: false };
await fire("session_start", { reason: "startup" });
const out = { prompt: await fire("before_agent_start", { prompt: "go" }) };
await fire("agent_start");
out.bash = await fire("tool_result", result("bash", { command: "gh pr create --fill" }));
out.read = await fire("tool_result", result("read", { path: "README.md" }));
out.failed = await fire("tool_result", result("bash", { command: "gh pr create --fill" }, true));
out.settle = process.env.HARNESS_OUTCOME === "skipped" ? [] : [
  await fire("agent_before_settle", settle),
  await fire("agent_before_settle", settle),
];
await fire("agent_settled");
for (const [id, tick] of [...timers].slice(0, 1)) {
  timers.delete(id);
  await tick();
}
out.polling = timers.size;
await fire("session_shutdown", { reason: "quit" });
console.log(JSON.stringify({ ...out, notes, sent, delays, left: timers.size }));
"""


def run_harness(sandbox, mode="rpc", outcome="completed"):
    """Load pr-tracker.ts in node against a fake Pi event API and fire one run through it:
    a prompt, a bash result, another tool's result, a failed bash result, two
    agent_before_settle (unless `outcome` is "skipped", as for an aborted run), the settle,
    one poll and the session's end."""
    stripped = strip_types(PR_TRACKER)
    assert stripped.returncode == 0, stripped.stderr
    module = sandbox.root / "pr-tracker.mjs"
    module.write_text(stripped.stdout)
    done = subprocess.run(
        ["node", "--input-type=module", "-e", HARNESS, str(module)],
        capture_output=True,
        text=True,
        env={**sandbox.env, "HARNESS_MODE": mode, "HARNESS_OUTCOME": outcome},
        cwd=sandbox.work,
        timeout=30,
    )
    assert (done.returncode, done.stderr) == (0, "")
    return json.loads(done.stdout)


needs_strip_types = pytest.mark.skipif(not node_strips_types(), reason="needs node 22.13 or later")

URL = "https://github.com/owner/repo/pull/7\n"
BASE = {"session_id": "pi-session", "cwd": "/work"}
APPENDED = {"content": [{"type": "text", "text": URL}, {"type": "text", "text": f"\n\n{NEWS}"}]}
POLL_MS = 30_000
NOTHING = {
    "prompt": None,
    "bash": None,
    "read": None,
    "failed": None,
    "settle": [None, None],
    "polling": 0,
    "notes": [],
    "sent": [],
    "delays": [],
    "left": 0,
}


def stop_call(active=None):
    payload = {**BASE, "hook_event_name": "Stop"}
    return (STOP, payload if active is None else {**payload, "stop_hook_active": active})


@needs_strip_types
def test_pr_tracker_delivers_on_the_prompt_and_every_tool_result(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub()
    result = run_harness(sandbox)
    assert result["prompt"] == {"message": MESSAGE}
    assert result["bash"] == result["read"] == result["failed"] == APPENDED
    bash = {"tool_name": "bash", "tool_input": {"command": "gh pr create --fill"}}
    assert sandbox.calls()[:4] == [
        (AS_PI, {**BASE, "hook_event_name": "UserPromptSubmit"}),
        (AS_PI, {**BASE, "hook_event_name": "PostToolUse", **bash, "tool_response": URL}),
        (
            AS_PI,
            {
                **BASE,
                "hook_event_name": "PostToolUse",
                "tool_name": "read",
                "tool_input": {"path": "README.md"},
                "tool_response": URL,
            },
        ),
        (AS_PI, {**BASE, "hook_event_name": "PostToolUseFailure", **bash, "error": URL}),
    ]


@needs_strip_types
def test_pr_tracker_shows_news_at_the_end_of_a_run_and_keeps_polling(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub()
    result = run_harness(sandbox)
    assert result["settle"] == [None, None]
    assert result["notes"] == [[NEWS, "info"]] * 2
    assert sandbox.calls()[4:] == [stop_call(False), stop_call(False), stop_call()]
    assert (result["sent"], result["delays"], result["polling"]) == ([], [POLL_MS] * 2, 1)
    assert result["left"] == 0, "session_shutdown stops the poll"


@needs_strip_types
def test_pr_tracker_continues_a_run_once_for_failing_checks(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub("wake", wake_on=1)
    result = run_harness(sandbox)
    entry = {"type": "custom_message", **MESSAGE}
    assert result["settle"] == [{"entries": [entry], "continue": True}, None]
    assert sandbox.calls()[4:] == [stop_call(False), stop_call(True), stop_call()]
    assert (result["notes"], result["sent"]) == ([], [])


@needs_strip_types
def test_pr_tracker_wakes_an_idle_session_for_failing_checks(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub("wake", wake_on=3)
    result = run_harness(sandbox)
    assert result["settle"] == [None, None]
    assert result["sent"] == [[MESSAGE, {"triggerTurn": True}]]
    assert (result["delays"], result["polling"]) == ([POLL_MS], 0)


@needs_strip_types
@pytest.mark.parametrize(
    ("mode", "outcome"),
    [("print", "completed"), ("json", "completed"), ("tui", "error"), ("tui", "skipped")],
)
def test_pr_tracker_polls_only_after_a_completed_run_in_modes_that_stay_open(
    tmp_path, mode, outcome
):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub("wake", wake_on=3)
    result = run_harness(sandbox, mode, outcome)
    assert (result["delays"], result["sent"]) == ([], [])
    if outcome == "error":
        assert sandbox.calls()[4:] == [stop_call(True), stop_call(True)]


@needs_strip_types
def test_pr_tracker_without_the_cli_does_nothing(tmp_path):
    assert run_harness(PrTrackerSandbox(tmp_path, "node")) == NOTHING


@needs_strip_types
def test_pr_tracker_ignores_a_broken_cli(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub("broken")
    result = run_harness(sandbox)
    assert result == {**NOTHING, "delays": [POLL_MS] * 2, "polling": 1}
    assert len(sandbox.calls()) == 7


@needs_strip_types
def test_pr_tracker_finds_the_cli_in_the_fallback_dirs(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "node")
    sandbox.stub()
    fallback = tmp_path / "fallback"
    (sandbox.bin / "pr-tracker").rename(fallback.mkdir() or fallback / "pr-tracker")
    sandbox.env["PR_TRACKER_HOOK_FALLBACK_PATH"] = str(fallback)
    assert run_harness(sandbox)["notes"] == [[NEWS, "info"]] * 2


# A test-only extension: Pi's faux provider stands in for a model. It asks for one bash
# call, says it's done, and then repeats whatever it was last sent.
FAUX_MODEL = """
import { fauxAssistantMessage, fauxProvider, fauxToolCall } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
\tconst faux = fauxProvider();
\tfaux.setResponses([
\t\tfauxAssistantMessage(fauxToolCall("bash", { command: process.env.FAUX_COMMAND })),
\t\tfauxAssistantMessage("done"),
\t\t(context) => {
\t\t\tconst { content } = context.messages[context.messages.length - 1];
\t\t\tconst parts = typeof content === "string" ? [{ text: content }] : content;
\t\t\treturn fauxAssistantMessage(`saw: ${parts.map((p) => p.text ?? "").join("")}`);
\t\t},
\t]);
\tpi.registerProvider(faux.provider);
}
"""


FAUX_FLAGS = ("--provider", "faux", "--model", "faux-1")
FAUX_COMMAND = "echo https://github.com/owner/repo/pull/7; echo $PI_SESSION_ID"


def run_pi_turn(sandbox, settles=1, extension=None, command=FAUX_COMMAND):
    """A real Pi in RPC mode, with a faux model that runs one bash `command`, prompted once
    and read until it has settled `settles` times. Loads the package installed in a
    throwaway home, or only `extension`. Returns Pi's output records."""
    agent = sandbox.home / ".pi" / "agent"
    agent.mkdir(parents=True)
    packages = [str(ROOT)] if extension is None else []
    (agent / "settings.json").write_text(json.dumps({"packages": packages}))
    faux = sandbox.root / "faux.ts"
    faux.write_text(FAUX_MODEL)
    env = {
        **sandbox.env,
        "PI_CODING_AGENT_DIR": str(agent),
        "PI_CODING_AGENT_SESSION_DIR": str(sandbox.home / "sessions"),
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
        "FAUX_COMMAND": command,
    }
    extensions = ["-e", str(extension)] if extension else []
    pi = subprocess.Popen(
        ["pi", "--mode", "rpc", "--no-session", *extensions, "-e", str(faux), *FAUX_FLAGS],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=sandbox.work,
        env=env,
    )
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in pi.stdout], daemon=True).start()
    records = []
    try:
        pi.stdin.write('{"id":"1","type":"prompt","message":"go"}\n')
        pi.stdin.flush()
        deadline = time.monotonic() + 60
        while sum(r.get("type") == "agent_settled" for r in records) < settles:
            records.append(json.loads(lines.get(timeout=max(deadline - time.monotonic(), 0))))
    finally:
        pi.stdin.close()
        try:
            pi.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pi.kill()
    assert pi.stderr.read() == ""
    return records


def messages(records, role):
    return [
        record["message"]
        for record in records
        if record.get("type") == "message_end" and record["message"]["role"] == role
    ]


def tool_results(records):
    return [message["content"] for message in messages(records, "toolResult")]


def replies(records):
    return [
        "".join(part.get("text", "") for part in message["content"])
        for message in messages(records, "assistant")
    ]


def delivered(records):
    """The messages of its own that pr-tracker put in the model's context."""
    entries = [
        record["entry"]
        for record in records
        if record.get("type") == "entry_appended" and record["entry"]["type"] == "custom_message"
    ]
    return [(m["customType"], m["content"]) for m in messages(records, "custom") + entries]


@needs_pi
def test_pi_runs_pr_tracker_on_a_real_run(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "pi", "node")
    sandbox.stub()
    records = run_pi_turn(sandbox)
    [(prompt_args, prompt), (post_args, post), (stop_args, stop)] = sandbox.calls()
    session = post["session_id"]
    assert session and prompt["session_id"] == stop["session_id"] == session
    assert (prompt_args, post_args, stop_args) == (AS_PI, AS_PI, STOP)
    assert prompt["hook_event_name"] == "UserPromptSubmit"
    assert (stop["hook_event_name"], stop["stop_hook_active"]) == ("Stop", False)
    output = f"https://github.com/owner/repo/pull/7\n{session}\n"
    assert post["tool_response"] == output, "PI_SESSION_ID is the session the hook reports"
    assert (post["tool_name"], post["tool_input"]) == ("bash", {"command": FAUX_COMMAND})
    assert delivered(records) == [("pr-tracker", NEWS)]
    assert tool_results(records) == [
        [{"type": "text", "text": output}, {"type": "text", "text": f"\n\n{NEWS}"}]
    ]
    [note] = [r for r in records if r.get("type") == "extension_ui_request"]
    assert (note["method"], note["message"]) == ("notify", NEWS)


@needs_pi
def test_pi_hands_pr_tracker_a_failed_bash_call(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "pi", "node")
    sandbox.stub()
    records = run_pi_turn(sandbox, command="echo https://github.com/owner/repo/pull/7; exit 3")
    post = sandbox.calls()[1][1]
    [result] = messages(records, "toolResult")
    [own, appended] = result["content"]
    assert result["isError"] and own["text"].startswith(URL)
    assert (post["hook_event_name"], post["error"]) == ("PostToolUseFailure", own["text"])
    assert "tool_response" not in post
    assert appended == APPENDED["content"][1]


@needs_pi
def test_pi_continues_a_real_run_for_failing_checks(tmp_path):
    sandbox = PrTrackerSandbox(tmp_path, "pi", "node")
    sandbox.stub("wake", wake_on=1)
    records = run_pi_turn(sandbox)
    stops = [payload for args, payload in sandbox.calls() if args == STOP]
    assert [payload["stop_hook_active"] for payload in stops] == [False, True]
    assert delivered(records) == [("pr-tracker", NEWS)]
    assert replies(records)[-2:] == ["done", f"saw: {NEWS}"]


@needs_pi
def test_pi_wakes_a_real_idle_session_for_failing_checks(tmp_path):
    source = PR_TRACKER.read_text()
    quick = source.replace("const POLL_MS = 30_000;", "const POLL_MS = 200;")
    assert quick != source
    extension = tmp_path / "pr-tracker.ts"
    extension.write_text(quick)
    sandbox = PrTrackerSandbox(tmp_path, "pi", "node")
    sandbox.stub("wake", wake_on=2)
    records = run_pi_turn(sandbox, settles=2, extension=extension)
    stops = [payload for args, payload in sandbox.calls() if args == STOP]
    assert [payload.get("stop_hook_active") for payload in stops[:3]] == [False, None, False]
    assert delivered(records) == [("pr-tracker", NEWS)]
    assert replies(records)[-2:] == ["done", f"saw: {NEWS}"]


@needs_pi
def test_pi_without_the_cli_leaves_the_bash_result_alone(tmp_path):
    records = run_pi_turn(PrTrackerSandbox(tmp_path, "pi", "node"))
    [[content]] = tool_results(records)
    assert content["text"].startswith("https://github.com/owner/repo/pull/7\n")
    assert not delivered(records)
    assert not [r for r in records if r.get("type") == "extension_ui_request"]


@needs_pi
def test_pi_filter_keeps_only_pr_trackers_skills(tmp_path):
    commands = run_pi(tmp_path, {"source": str(ROOT), "skills": ["plugins/pr-tracker/skills/*"]})
    assert {name for name in commands if name.startswith("skill:")} == {
        "skill:pr-tracker",
        "skill:prs",
    }
    assert "statusline" in commands
