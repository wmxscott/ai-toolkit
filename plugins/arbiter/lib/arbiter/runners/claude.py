"""Judge runner backed by headless Claude Code."""

import json
import subprocess
from pathlib import Path

from .. import prompts
from ..config import Task
from ..constants import CLAUDE_RUNNER
from ..verdicts import Verdict, extract_json
from .base import RunContext, Runner


def sandbox_settings(root: Path, scratch: Path) -> dict:
    """Filesystem policy for a judge, enforced by the OS rather than by prompt.

    Two syntax traps live here, both found the hard way:

    - ``Write(path)`` deny rules are ignored by file permission checks. Only
      ``Edit(path)`` applies, and it covers every file-editing tool.
    - Sandbox filesystem paths are plain absolutes while permission rules take a
      ``//`` prefix -- two conventions inside one file.

    ``allowUnsandboxedCommands: false`` is strict mode: a blocked command cannot
    be retried outside the sandbox.

    The judge's output style is inlined into its system prompt, so the named
    style is pinned to ``default``: a style the user set for their own sessions
    must not reshape a judge's verdict.
    """
    return {
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {"denyWrite": [str(root)], "allowWrite": [str(scratch)]},
        },
        "permissions": {"deny": [f"Edit(/{root}/**)"], "defaultMode": "auto"},
        "outputStyle": "default",
    }


class ClaudeRunner(Runner):
    name = CLAUDE_RUNNER

    # --bare would trim the ~21k tokens of tool definitions loaded on every
    # spawn, but it never reads keychain or OAuth credentials and so is
    # unusable without an API key. These flags are the next best thing.
    BASE_FLAGS = (
        "--output-format",
        "json",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--permission-mode",
        "auto",
    )

    def execute(self, task: Task, ctx: RunContext) -> Verdict:
        timeout = self.budgeted_timeout(task, ctx)
        if timeout <= 0:
            return Verdict.failure(task, "engine budget exhausted before task started")

        scratch = ctx.scratch_for(task.name)
        settings_path = scratch / "settings.json"
        settings_path.write_text(json.dumps(sandbox_settings(ctx.root, scratch), indent=2))

        cmd = [
            "claude",
            "-p",
            "--settings",
            str(settings_path),
            # Deliberately no --add-dir for the repository. The sandbox permits
            # reads outside the workspace, so Bash reaches the repo anyway, and
            # --add-dir would make Claude Code scaffold a `.claude/` directory
            # inside the tree under review.
            *self.BASE_FLAGS,
            "--system-prompt",
            prompts.build(task, ctx.root, scratch, with_style=True),
        ]
        if task.model:
            cmd += ["--model", task.model]
        if task.effort:
            cmd += ["--effort", task.effort]

        try:
            # cwd is the scratch dir, not the repository: Claude Code writes a
            # `.claude/` bookkeeping directory beside its cwd, and that must not
            # land in the tree under review.
            proc = self.run_process(
                cmd,
                cwd=scratch,
                timeout=timeout,
                env=ctx.child_env,
                stdin="Review the current change set and return your verdict JSON.",
            )
        except subprocess.TimeoutExpired:
            return Verdict.failure(task, f"timed out after {timeout}s")

        if proc.returncode != 0:
            return Verdict.failure(
                task, f"claude exited {proc.returncode}", (proc.stderr or proc.stdout)[-2000:]
            )

        # --output-format json wraps the model's text in a result envelope.
        envelope = extract_json(proc.stdout) or {}
        text = envelope.get("result", proc.stdout)
        return Verdict.from_payload(task, extract_json(text), "claude returned no parsable verdict")
