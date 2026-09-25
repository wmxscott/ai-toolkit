"""Task selection, concurrent execution, and the wall-clock budget."""

import concurrent.futures
import os
import time

from . import runners
from .config import Config, Task
from .constants import CHILD_ENV
from .errors import ArbiterError
from .repository import Repository
from .state import State
from .verdicts import Verdict


class Budget:
    """Wall-clock ceiling for a whole gate run.

    A Stop hook that exceeds its timeout renders no decision and the turn ends
    normally -- a silent fail-open. The engine stays under that ceiling and
    reports exhaustion as an explicit failure instead.
    """

    def __init__(self, seconds: int):
        self.total = seconds
        self._started = time.monotonic()

    def remaining(self) -> int:
        return max(0, int(self.total - (time.monotonic() - self._started)))


class Engine:
    """Selects applicable tasks, runs them, and persists their verdicts."""

    def __init__(self, repo: Repository, config: Config):
        self.repo = repo
        self.config = config
        self.state = State(repo.root)
        self.budget = Budget(config.budget)

    @property
    def change_hash(self) -> str:
        return self.repo.change_hash

    @property
    def changed_paths(self) -> list[str]:
        return self.repo.changed_paths

    def applicable(self, only: str | None = None) -> list[Task]:
        return [
            t
            for t in self.config.tasks
            if t.enabled and (only is None or t.name == only) and t.applies_to(self.changed_paths)
        ]

    def _context(self) -> runners.RunContext:
        child_env = dict(os.environ)
        # Judge subprocesses must not re-enter the gate that spawned them.
        child_env[CHILD_ENV] = "1"
        return runners.RunContext(
            root=self.repo.root,
            child_env=child_env,
            remaining=self.budget.remaining,
            scratch_for=lambda name: self.state.scratch_for(self.change_hash, name),
        )

    @staticmethod
    def _execute_one(task: Task, ctx: runners.RunContext) -> Verdict:
        """A crashing runner must never fail open."""
        try:
            return runners.get(task.runner).execute(task, ctx)
        except ArbiterError as e:
            return Verdict.failure(task, str(e))
        except Exception as e:
            return Verdict.failure(task, f"runner error: {type(e).__name__}: {e}")

    def run(
        self,
        only: str | None = None,
        use_cache: bool = True,
        reuse_failures: bool = False,
    ) -> list[Verdict]:
        """Execute applicable tasks, reusing what the cache already answers.

        Verdicts are keyed by the change-set content hash, so a cache hit means
        the tree is byte-identical to when that verdict was produced.
        ``reuse_failures`` extends that reuse to failing verdicts, which is
        correct exactly when nothing has changed since they were rendered --
        the hook's case, where a turn that edited nothing would otherwise re-run
        every failing gate to reach the same answer. Manual runs leave it off,
        since asking to run is asking to re-run.
        """
        tasks = self.applicable(only)
        if not tasks:
            return []

        cached = self.state.load_verdicts(self.change_hash) if use_cache else {}
        results: list[Verdict] = []
        pending: list[Task] = []
        for task in tasks:
            hit = cached.get(task.name)
            if hit and (hit.get("ok") or reuse_failures):
                results.append(Verdict.from_cache(task, hit))
            else:
                pending.append(task)

        if pending:
            self.state.ensure()
            ctx = self._context()
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(pending)) as pool:
                futures = [pool.submit(self._execute_one, t, ctx) for t in pending]
                results += [f.result() for f in concurrent.futures.as_completed(futures)]

        merged = dict(cached)
        for verdict in results:
            merged[verdict.task.name] = verdict.to_dict()
        self.state.save_verdicts(self.change_hash, merged)

        order = {t.name: i for i, t in enumerate(tasks)}
        results.sort(key=lambda v: order.get(v.task.name, 0))
        return results

    @staticmethod
    def blocking(verdicts: list[Verdict]) -> list[Verdict]:
        return [v for v in verdicts if v.blocks]
