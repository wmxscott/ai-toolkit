"""Runner interface and shared execution context."""

import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import Task
from ..verdicts import Verdict


@dataclass
class RunContext:
    """Everything a runner needs, and nothing about how it was configured."""

    root: Path
    child_env: dict
    remaining: Callable[[], int]
    scratch_for: Callable[[str], Path]


class Runner(ABC):
    """Executes one task and returns its verdict.

    This is the framework's only extension point. Adding a runner -- another
    agent CLI, a local model, a remote service -- is a new subclass, not a
    change to the engine.
    """

    name: str

    @abstractmethod
    def execute(self, task: Task, ctx: RunContext) -> Verdict:
        """Run the task. Must not raise; return a failing Verdict instead."""

    @staticmethod
    def budgeted_timeout(task: Task, ctx: RunContext) -> int:
        """A task never outlives the engine's remaining budget."""
        return min(task.timeout, ctx.remaining())

    @staticmethod
    def run_process(
        cmd: list[str], *, cwd: Path, timeout: int, env: dict, stdin: str | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
