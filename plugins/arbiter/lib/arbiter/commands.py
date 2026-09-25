"""Subcommand implementations. Each returns a process exit code."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from .config import ConfigLoader
from .constants import BLOCK_LIMIT, CHILD_ENV, PROJECT_CONFIG, data_dirs
from .engine import Engine
from .errors import ConfigError
from .reporting import BOLD, DIM, GREEN, RED, Reporter
from .repository import Repository
from .state import State

EXIT_OK = 0
EXIT_BLOCK = 2


def _load(cwd: Path) -> Engine | None:
    """Resolve repository and config. None means there is nothing to gate."""
    repo = Repository.discover(cwd)
    if repo is None:
        return None
    config = ConfigLoader(repo.root).load()
    if not config:
        return None
    return Engine(repo, config)


def _hook_cwd(raw: str) -> Path:
    """The hook's cwd comes from its JSON payload, not the process."""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if isinstance(cwd, str) and os.path.isabs(cwd):
        return Path(cwd)
    return Path.cwd()


def _hold(state: State, key: str, message: str, report: str) -> dict:
    """Block the turn, unless the same block has already held it BLOCK_LIMIT times.

    Counting consecutive blocks per change-set hash tells an agent that is
    spinning from one that is iterating, which ``stop_hook_active`` cannot.
    """
    attempts = state.record_block(key)
    if attempts >= BLOCK_LIMIT:
        state.clear_blocks()
        return {
            "systemMessage": f"arbiter: released after {attempts} consecutive blocks on "
            f"an unchanged change set; still failing:\n{report}"
        }
    return {
        "decision": "block",
        "reason": f"{message} (attempt {attempts}/{BLOCK_LIMIT}). "
        f"Fix these, then finish:\n{report}",
    }


def _decide(cwd: Path) -> dict:
    repo = Repository.discover(cwd)
    if repo is None:
        return {}
    try:
        config = ConfigLoader(repo.root).load()
    except ConfigError as e:
        key = "config-" + hashlib.sha256(str(e).encode()).hexdigest()[:16]
        return _hold(State(repo.root), key, "arbiter: invalid configuration", f"  {e}")
    if not any(t.enabled for t in config.tasks):
        return {}

    engine = Engine(repo, config)
    if not engine.changed_paths:
        return {}

    # reuse_failures: a cache hit means the tree is byte-identical to when the
    # verdict was rendered, so a turn that produced no changes replays the last
    # decision instead of re-running gates to reach the same answer. Without
    # this, an idle turn re-runs every failing gate -- including judges.
    verdicts = engine.run(reuse_failures=True)
    failures = engine.blocking(verdicts)
    if not failures:
        engine.state.clear_blocks()
        return {}

    report = Reporter(color=False).render(verdicts)
    message = f"arbiter: {len(failures)} required gate(s) failed"
    return _hold(engine.state, engine.change_hash, message, report)


def hook(args) -> int:
    """Stop-hook entry point.

    Always exits 0 with one JSON object on stdout: ``{}`` lets the turn end,
    ``decision: block`` holds it open with the findings as the reason, and a
    ``systemMessage`` tells the user when arbiter lets a turn end over a
    problem. An internal error is reported that way too, never as a block: a
    bug in arbiter must not trap the session.
    """
    if os.environ.get(CHILD_ENV):
        decision = {}
    else:
        try:
            raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
            decision = _decide(_hook_cwd(raw))
        except Exception as e:
            decision = {
                "systemMessage": f"arbiter: internal error, this turn was not gated: "
                f"{type(e).__name__}: {e}"
            }
    print(json.dumps(decision))
    return EXIT_OK


def run(args) -> int:
    reporter = Reporter(color=sys.stdout.isatty())
    try:
        engine = _load(Path.cwd())
    except ConfigError as e:
        print(f"arbiter: {e}", file=sys.stderr)
        return EXIT_BLOCK
    if engine is None:
        print("arbiter: no configuration found; nothing to do")
        return EXIT_OK
    if not engine.changed_paths:
        print("arbiter: no changes to gate")
        return EXIT_OK

    print(
        f"{reporter.paint(BOLD, 'arbiter')} {reporter.paint(DIM, engine.change_hash)}  "
        f"{len(engine.changed_paths)} changed file(s)"
    )
    verdicts = engine.run(only=args.task, use_cache=not args.no_cache)
    if not verdicts:
        print("  no tasks apply to this change set")
        return EXIT_OK

    print(reporter.render(verdicts))
    failures = engine.blocking(verdicts)
    if failures:
        print(reporter.paint(RED, f"\n{len(failures)} required gate(s) failed"))
        return EXIT_BLOCK
    print(reporter.paint(GREEN, "\nall required gates passed"))
    return EXIT_OK


def plan(args) -> int:
    reporter = Reporter(color=sys.stdout.isatty())
    try:
        engine = _load(Path.cwd())
    except ConfigError as e:
        print(f"arbiter: {e}", file=sys.stderr)
        return EXIT_BLOCK
    if engine is None:
        print("arbiter: no configuration found")
        return EXIT_OK

    paths = engine.changed_paths
    cached = engine.state.load_verdicts(engine.change_hash)
    print(f"root:   {engine.repo.root}")
    print(f"hash:   {engine.change_hash}")
    print(f"files:  {len(paths)}")
    for path in paths[:40]:
        print(f"          {path}")
    if len(paths) > 40:
        print(f"          ... and {len(paths) - 40} more")

    print("tasks:")
    width = max((len(t.name) for t in engine.config.tasks), default=0)
    for task in engine.config.tasks:
        reason = task.skip_reason(paths, bool(cached.get(task.name, {}).get("ok")))
        flag = "" if task.required else " [advisory]"
        print(
            f"  {task.name:<{width}}  {task.runner:<7}{flag:<12} "
            f"{reporter.paint(DIM, reason or 'would run')}"
        )
    return EXIT_OK


def status(args) -> int:
    try:
        engine = _load(Path.cwd())
    except ConfigError as e:
        print(f"arbiter: {e}", file=sys.stderr)
        return EXIT_BLOCK
    if engine is None:
        print("arbiter: no configuration found")
        return EXIT_OK

    cached = engine.state.load_verdicts(engine.change_hash)
    if not cached:
        print(f"arbiter: no cached verdicts for {engine.change_hash}")
        return EXIT_OK
    print(f"cached verdicts for {engine.change_hash}:")
    print(json.dumps(cached, indent=2))
    return EXIT_OK


def _available_templates() -> dict[str, Path]:
    """Template name to file. A user template shadows a built-in one of the same name."""
    found: dict[str, Path] = {}
    for base in reversed(data_dirs()):
        directory = base / "templates"
        if directory.is_dir():
            found.update({p.stem: p for p in directory.glob("*.toml")})
    return dict(sorted(found.items()))


def init(args) -> int:
    """Copy a template into the repository as its project config."""
    templates = _available_templates()
    if not templates:
        searched = ", ".join(str(base / "templates") for base in data_dirs())
        print(f"arbiter: no templates found in {searched}", file=sys.stderr)
        return EXIT_BLOCK

    if not args.template:
        print("available templates:")
        for name in templates:
            print(f"  {name}")
        print(f"\nusage: arbiter init <template>   (writes ./{PROJECT_CONFIG})")
        return EXIT_OK

    source = templates.get(args.template)
    if source is None:
        names = ", ".join(templates)
        print(
            f"arbiter: no template named '{args.template}'; available: {names}",
            file=sys.stderr,
        )
        return EXIT_BLOCK

    # Write to the repository root, not the current directory: gates are
    # resolved from the git root, so a config anywhere else would be ignored.
    repo = Repository.discover(Path.cwd())
    root = repo.root if repo else Path.cwd()
    target = root / PROJECT_CONFIG

    if target.exists() and not args.force:
        print(
            f"arbiter: {target} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return EXIT_BLOCK

    shutil.copyfile(source, target)
    print(f"arbiter: wrote {target} from template '{args.template}'")
    print("  review it, then run `arbiter plan` to see what it will gate")
    if repo is None:
        print("  note: not a git repository, so gates will not run until it is one")
    return EXIT_OK


def clean(args) -> int:
    repo = Repository.discover(Path.cwd())
    if repo is None:
        print("arbiter: not a git repository")
        return EXIT_OK

    state = State(repo.root)
    removed = [state.purge_scratch()]
    try:
        removed.append(state.purge_repo_state())
    except ValueError as e:
        print(f"arbiter: {e}", file=sys.stderr)
        return EXIT_BLOCK

    removed = [p for p in removed if p]
    for path in removed:
        print(f"arbiter: removed {path}")
    if not removed:
        print("arbiter: nothing to clean")
    return EXIT_OK
