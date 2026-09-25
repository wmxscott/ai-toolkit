"""Deterministic gates: lint, tests, build, anything with an exit code."""

import subprocess

from ..config import Task
from ..constants import SHELL_RUNNER
from ..verdicts import Verdict
from .base import RunContext, Runner


class ShellRunner(Runner):
    name = SHELL_RUNNER

    def execute(self, task: Task, ctx: RunContext) -> Verdict:
        timeout = self.budgeted_timeout(task, ctx)
        if timeout <= 0:
            return Verdict.failure(task, "engine budget exhausted before task started")

        try:
            proc = subprocess.run(
                task.command,
                shell=True,
                cwd=str(ctx.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=ctx.child_env,
            )
        except subprocess.TimeoutExpired:
            return Verdict.failure(task, f"timed out after {timeout}s")

        if proc.returncode == 0:
            return Verdict(task=task, ok=True, summary="passed")
        output = (proc.stdout + proc.stderr).strip()
        return Verdict.failure(task, f"exit {proc.returncode}", output[-4000:])
