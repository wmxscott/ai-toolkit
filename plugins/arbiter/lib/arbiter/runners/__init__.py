"""Runner registry.

Adding a runner means adding a subclass and registering it here; nothing in the
engine changes.
"""

from .base import RunContext, Runner
from .claude import ClaudeRunner
from .codex import CodexRunner
from .shell import ShellRunner

REGISTRY: dict[str, Runner] = {r.name: r() for r in (ShellRunner, ClaudeRunner, CodexRunner)}


def get(name: str) -> Runner:
    return REGISTRY[name]


__all__ = [
    "REGISTRY",
    "ClaudeRunner",
    "CodexRunner",
    "RunContext",
    "Runner",
    "ShellRunner",
    "get",
]
