"""Paths, defaults and limits.

Every tunable lives here so the operational envelope is readable in one place.
Paths derived from the environment are functions, read at call time.
"""

import os
from pathlib import Path

# Set on judge subprocesses. Both claude and codex fire their own Stop hooks, so
# without this guard a judge re-enters the gate that spawned it.
CHILD_ENV = "ARBITER_CHILD"

# Per-repository state (verdict cache, block counter). Judges never write here.
STATE_DIRNAME = ".arbiter"

CONFIG_BASENAMES = ("arbiter.toml", "arbiter.local.toml")
PROJECT_CONFIG = CONFIG_BASENAMES[0]
DEFAULTS_BASENAME = "defaults.toml"

# The built-in layer ships inside the plugin: lib/arbiter/ -> lib/ -> plugin root.
BUILTIN_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


def user_config_dir() -> Path:
    """The user layer: overrides the built-in defaults, judges, styles and templates."""
    return _xdg("XDG_CONFIG_HOME", ".config") / "arbiter"


def state_home() -> Path:
    """Judge scratch lives here, outside the repository.

    A judge's sandbox denies writes to the repo root, and a nested allowWrite
    does not override that deny: scratch inside the repo is unwritable.
    """
    return _xdg("XDG_STATE_HOME", ".local/state") / "arbiter"


def data_dirs() -> list[Path]:
    """Where bundled data is looked up, user first."""
    return [user_config_dir(), BUILTIN_DIR]


DEFAULT_TIMEOUT = 120
DEFAULT_OUTPUT_STYLE = "verdict"

# The Stop hook ceiling is 600s, and a timed-out hook renders NO decision -- it
# fails open silently. Stay well under it and report exhaustion explicitly.
ENGINE_BUDGET = 540
HOOK_TIMEOUT = 600

# Consecutive blocks on an identical change set before releasing the turn. The
# agent is spinning rather than fixing; trapping the session helps nobody.
BLOCK_LIMIT = 3

SHELL_RUNNER = "shell"
CLAUDE_RUNNER = "claude"
CODEX_RUNNER = "codex"
JUDGE_RUNNERS = (CLAUDE_RUNNER, CODEX_RUNNER)
RUNNERS = (SHELL_RUNNER, *JUDGE_RUNNERS)

# Reasoning effort accepted by each judge runner. Claude enumerates these in
# `--effort`; Codex takes any string for model_reasoning_effort and defers
# rejection to the provider, so arbiter validates it here instead -- a typo
# should fail at config load, not halfway through a judge.
EFFORT_LEVELS = {
    CLAUDE_RUNNER: ("low", "medium", "high", "xhigh", "max"),
    CODEX_RUNNER: ("minimal", "low", "medium", "high", "xhigh"),
}
