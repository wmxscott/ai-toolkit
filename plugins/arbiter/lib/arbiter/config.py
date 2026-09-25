"""Task definitions and three-layer configuration loading."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .constants import (
    BUILTIN_DIR,
    CONFIG_BASENAMES,
    DEFAULT_OUTPUT_STYLE,
    DEFAULT_TIMEOUT,
    DEFAULTS_BASENAME,
    EFFORT_LEVELS,
    ENGINE_BUDGET,
    HOOK_TIMEOUT,
    RUNNERS,
    SHELL_RUNNER,
    data_dirs,
    user_config_dir,
)
from .errors import ConfigError
from .patterns import matches


@dataclass
class Task:
    """One gate. The unit of both configuration and execution."""

    name: str
    runner: str
    source: str
    command: str | None = None
    paths: list[str] = field(default_factory=list)
    timeout: int = DEFAULT_TIMEOUT
    required: bool = True
    enabled: bool = True
    agent: str | None = None
    prompt: str | None = None
    prompt_file: str | None = None
    output_style: str = DEFAULT_OUTPUT_STYLE
    model: str | None = None
    effort: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict, source: str) -> "Task":
        name = data.get("name")
        if not name:
            raise ConfigError(f"task in {source}: missing required field 'name'")
        return cls(
            name=name,
            runner=data.get("runner", ""),
            source=source,
            command=data.get("command"),
            paths=list(data.get("paths") or []),
            timeout=int(data.get("timeout", DEFAULT_TIMEOUT)),
            required=bool(data.get("required", True)),
            enabled=bool(data.get("enabled", True)),
            agent=data.get("agent"),
            prompt=data.get("prompt"),
            prompt_file=data.get("prompt_file"),
            output_style=data.get("output_style", DEFAULT_OUTPUT_STYLE),
            model=data.get("model"),
            effort=data.get("effort"),
            raw=data,
        )

    def validate(self) -> None:
        where = f"task '{self.name}' ({self.source})"
        if self.runner not in RUNNERS:
            raise ConfigError(
                f"{where}: runner must be one of {', '.join(RUNNERS)}, got {self.runner!r}"
            )
        if self.prompt and self.prompt_file:
            raise ConfigError(
                f"{where}: 'prompt' and 'prompt_file' are mutually exclusive; declare one"
            )
        if self.runner == SHELL_RUNNER:
            if not self.command:
                raise ConfigError(f"{where}: runner 'shell' requires 'command'")
            if self.effort:
                raise ConfigError(f"{where}: 'effort' applies to judge runners only, not 'shell'")
        else:
            if not (self.agent or self.prompt or self.prompt_file):
                raise ConfigError(
                    f"{where}: judge runners require one of 'agent', 'prompt', or 'prompt_file'"
                )
            allowed = EFFORT_LEVELS.get(self.runner, ())
            if self.effort and self.effort not in allowed:
                raise ConfigError(
                    f"{where}: effort must be one of {', '.join(allowed)} "
                    f"for runner '{self.runner}', got {self.effort!r}"
                )
        if self.timeout <= 0:
            raise ConfigError(f"{where}: 'timeout' must be positive")

    def applies_to(self, paths: list[str]) -> bool:
        """No globs means the task always runs."""
        if not self.paths:
            return True
        return any(matches(p, self.paths) for p in paths)

    def skip_reason(self, paths: list[str], cached_ok: bool) -> str | None:
        """Why this task will not run, or None if it will."""
        if not self.enabled:
            return "disabled"
        if not self.applies_to(paths):
            return f"no path match ({', '.join(self.paths)})"
        if cached_ok:
            return "cached pass"
        return None


@dataclass
class Config:
    tasks: list[Task]
    budget: int = ENGINE_BUDGET

    def __bool__(self) -> bool:
        return bool(self.tasks)


def _load_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: {e}") from e


class ConfigLoader:
    """Merges the configuration layers.

    Built-in defaults, the user's defaults, the project's committed config, then
    a gitignored local override. Later layers win, merged per task by name so a
    later layer can adjust a single field without restating the task.

    The built-in layer only joins when another layer exists: a repository with
    no config of its own, for a user with none either, has nothing to gate.
    """

    def __init__(self, root: Path):
        self.root = root

    def layer_paths(self) -> list[Path]:
        user = user_config_dir() / DEFAULTS_BASENAME
        paths = [user] if user.is_file() else []
        paths += [p for p in (self.root / b for b in CONFIG_BASENAMES) if p.is_file()]
        builtin = BUILTIN_DIR / DEFAULTS_BASENAME
        if paths and builtin.is_file():
            paths.insert(0, builtin)
        return paths

    def load(self) -> Config:
        layers = [(p, _load_toml(p)) for p in self.layer_paths()]
        if not layers:
            return Config(tasks=[])

        budget = ENGINE_BUDGET
        merged: dict[str, dict] = {}
        order: list[str] = []
        for path, data in layers:
            settings = data.get("arbiter", {})
            if not isinstance(settings, dict):
                raise ConfigError(f"{path}: [arbiter] must be a table")
            budget = settings.get("budget", budget)
            if not isinstance(budget, int) or isinstance(budget, bool):
                raise ConfigError(f"{path}: 'budget' must be an integer")
            if not 0 < budget < HOOK_TIMEOUT:
                raise ConfigError(
                    f"{path}: 'budget' must be between 1 and {HOOK_TIMEOUT - 1} seconds, "
                    f"below the Stop hook's {HOOK_TIMEOUT}s ceiling"
                )
            entries = data.get("task", [])
            if not isinstance(entries, list):
                raise ConfigError(f"{path}: 'task' must be an array of tables ([[task]])")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ConfigError(f"{path}: each [[task]] must be a table")
                name = entry.get("name")
                if not name:
                    raise ConfigError(f"task in {path}: missing required field 'name'")
                if name in merged:
                    merged[name] = {**merged[name], **entry, "__source__": str(path)}
                else:
                    merged[name] = {**entry, "__source__": str(path)}
                    order.append(name)

        tasks = []
        for name in order:
            data = dict(merged[name])
            source = data.pop("__source__")
            task = Task.from_dict(data, source)
            task.validate()
            tasks.append(task)
        return Config(tasks=tasks, budget=budget)


def find_data(*parts: str) -> Path | None:
    """A bundled data file, from the user's config dir if present, else built in."""
    for base in data_dirs():
        path = base.joinpath(*parts)
        if path.is_file():
            return path
    return None


def resolve_persona(name: str, root: Path) -> Path:
    """Resolve an ``agent`` name to a persona file, project first."""
    candidates = [
        root / ".arbiter" / "judges" / f"{name}.md",
        root / "judges" / f"{name}.md",
        *(base / "judges" / f"{name}.md" for base in data_dirs()),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise ConfigError(
        f"agent '{name}' not found; looked in: " + ", ".join(str(c) for c in candidates)
    )


def resolve_output_style(name: str, root: Path) -> str:
    """The body of a judge output style, without its frontmatter. Empty name: none."""
    if not name:
        return ""
    candidates = [
        root / ".arbiter" / "output-styles" / f"{name}.md",
        *(base / "output-styles" / f"{name}.md" for base in data_dirs()),
    ]
    for c in candidates:
        if c.is_file():
            return strip_frontmatter(c.read_text()).strip()
    raise ConfigError(
        f"output style '{name}' not found; looked in: " + ", ".join(str(c) for c in candidates)
    )


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def resolve_instruction(task: Task, root: Path) -> str:
    """Compose a judge's instruction from its persona and prompt."""
    parts: list[str] = []
    if task.agent:
        parts.append(resolve_persona(task.agent, root).read_text())
    if task.prompt:
        parts.append(task.prompt)
    elif task.prompt_file:
        path = (root / task.prompt_file).resolve()
        if not path.is_file():
            raise ConfigError(f"task '{task.name}': prompt_file not found: {path}")
        parts.append(path.read_text())
    return "\n\n".join(parts).strip()
