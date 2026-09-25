"""Judge runner backed by Codex, for cross-model review."""

import subprocess

from .. import prompts
from ..config import Task, find_data
from ..constants import CODEX_RUNNER
from ..verdicts import Verdict, extract_json
from .base import RunContext, Runner


class CodexRunner(Runner):
    """Runs a judge under a different model family than the one being audited.

    Isolation comes from geometry: the workspace is the scratch directory, so
    the repository is read-only purely by sitting outside it. ``--sandbox
    read-only`` is deliberately not used -- it also blocks scratch writes, which
    would leave the judge unable to write temp files.

    Known limitation: Codex treats /tmp and $TMPDIR as writable regardless of
    workspace, so a repository under a temp directory is not protected.
    """

    name = CODEX_RUNNER

    def execute(self, task: Task, ctx: RunContext) -> Verdict:
        timeout = self.budgeted_timeout(task, ctx)
        if timeout <= 0:
            return Verdict.failure(task, "engine budget exhausted before task started")

        scratch = ctx.scratch_for(task.name)
        out_file = scratch / "verdict.json"

        cmd = [
            "codex",
            "exec",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(scratch),
            "--skip-git-repo-check",
            "--ephemeral",
            "-o",
            str(out_file),
        ]
        schema = find_data("schema", "verdict.schema.json")
        if schema:
            cmd += ["--output-schema", str(schema)]
        if task.model:
            cmd += ["-m", task.model]
        if task.effort:
            # Codex has no --effort flag; reasoning effort is a config override.
            cmd += ["-c", f'model_reasoning_effort="{task.effort}"']

        try:
            proc = self.run_process(
                cmd,
                cwd=scratch,
                timeout=timeout,
                env=ctx.child_env,
                stdin=prompts.build(task, ctx.root, scratch),
            )
        except subprocess.TimeoutExpired:
            return Verdict.failure(task, f"timed out after {timeout}s")

        payload = extract_json(out_file.read_text()) if out_file.exists() else None
        if payload is None:
            payload = extract_json(proc.stdout)
        if payload is None and proc.returncode != 0:
            return Verdict.failure(
                task, f"codex exited {proc.returncode}", (proc.stderr or proc.stdout)[-2000:]
            )
        return Verdict.from_payload(task, payload, "codex returned no parsable verdict")
