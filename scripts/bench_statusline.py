#!/usr/bin/env python3
"""Benchmark a Claude Code statusline command under many concurrent sessions.

Each simulated session pipes session JSON into `sh -c <command>` every
--interval seconds, from its own thread, with its working directory in one of
--worktrees scratch git repos. Reports redraw wall time, child CPU and an
approximate machine-wide process start rate.
"""

import argparse
import json
import math
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Bench",
    "GIT_AUTHOR_EMAIL": "bench@example.com",
    "GIT_COMMITTER_NAME": "Bench",
    "GIT_COMMITTER_EMAIL": "bench@example.com",
}


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        check=True,
        capture_output=True,
    )


def make_repo(path: Path) -> None:
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / "src").mkdir()
    for name in ("README.md", "src/app.py", "src/util.py"):
        (path / name).write_text("".join(f"line {n}\n" for n in range(40)))
    git(path, "add", ".")
    git(path, "commit", "-q", "--no-gpg-sign", "-m", "init")
    git(path, "checkout", "-q", "-b", "feature")
    with (path / "src/app.py").open("a") as f:
        f.write("added 1\nadded 2\nadded 3\n")
    (path / "src/util.py").write_text("".join(f"line {n}\n" for n in range(30)))
    (path / "notes.txt").write_text("untracked\n")
    (path / "src/new.py").write_text("untracked\n")


def session_json(n: int, cwd: Path) -> bytes:
    now = int(time.time())
    data = {
        "session_id": str(uuid.uuid4()),
        "transcript_path": str(cwd / ".transcript.jsonl"),
        "cwd": str(cwd),
        "version": "2.1.0",
        "model": {"id": "claude-opus-4-7", "display_name": "Claude Opus 4.7"},
        "workspace": {"current_dir": str(cwd), "project_dir": str(cwd)},
        "vim": {"mode": "insert" if n % 2 else "normal"},
        "effort": {"level": "high"},
        "output_style": {"name": "default"},
        "context_window": {
            "used_percentage": 10 + (n * 7) % 80,
            "context_window_size": 200000,
        },
        "exceeds_200k_tokens": False,
        "cost": {
            "total_cost_usd": 0.5 + n * 0.37,
            "total_duration_ms": 60000 + n * 45000,
            "total_lines_added": 12 * n,
            "total_lines_removed": 3 * n,
        },
        "rate_limits": {
            "five_hour": {"used_percentage": 23.5, "resets_at": now + 2 * 3600 + 14 * 60},
            "seven_day": {"used_percentage": 41.2, "resets_at": now + 5 * 86400},
        },
    }
    return json.dumps(data).encode()


@dataclass
class Session:
    payload: bytes
    offset: float
    walls: list[float] = field(default_factory=list)
    failures: int = 0
    skipped: int = 0
    error: str = ""


def command_env() -> dict[str, str]:
    env = dict(os.environ)
    prefix = env.pop("_PYENV_INSTALL_PREFIX", None)
    if prefix is None:
        return env
    # Run through a pyenv shim, `pyenv exec` put the real interpreter first on PATH and pinned
    # PYENV_VERSION, so a `python3` in the command would skip the shim chain being measured.
    root = env.get("PYENV_ROOT", prefix)
    roots = (prefix, os.path.join(root, "versions", ""), os.path.join(root, "plugins", ""))
    path = env.get("PATH", "").split(os.pathsep)
    while path and path[0].startswith(roots):
        path.pop(0)
    env["PATH"] = os.pathsep.join(path)
    for name in list(env):
        if name in ("PYENV_VERSION", "PYENV_DIR", "PYENV_HOOK_PATH") or name.startswith(
            "_PYENV_SHIM_PATHS_"
        ):
            del env[name]
    return env


def run_session(
    s: Session, command: str, env: dict[str, str], start: float, end: float, interval: float
) -> None:
    tick = start + s.offset
    while tick < end:
        delay = tick - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        t0 = time.perf_counter()
        proc = subprocess.run(
            ["sh", "-c", command],
            input=s.payload,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        s.walls.append(time.perf_counter() - t0)
        if proc.returncode:
            s.failures += 1
            s.error = s.error or proc.stderr.decode(errors="replace").strip()[-300:]
        now = time.monotonic()
        tick += interval
        while tick <= now:
            if tick < end:
                s.skipped += 1
            tick += interval


def pid_max() -> int:
    try:
        return int(Path("/proc/sys/kernel/pid_max").read_text())
    except OSError:
        return 99999


def probe_pid() -> int:
    proc = subprocess.Popen(["/bin/sh", "-c", ":"])
    proc.wait()
    return proc.pid


def pid_advance(before: int, after: int) -> int:
    # The probe that read `after` is itself one start.
    return (after - before) % pid_max() - 1


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def bench(args: argparse.Namespace) -> dict:
    baseline = min(args.baseline, args.seconds)
    p0, t0 = probe_pid(), time.monotonic()
    time.sleep(baseline)
    p1, t1 = probe_pid(), time.monotonic()
    idle_rate = pid_advance(p0, p1) / (t1 - t0)

    with tempfile.TemporaryDirectory(prefix="bench-statusline-") as tmp:
        root = Path(os.path.realpath(tmp))
        repos = [root / f"project-{n + 1}" for n in range(args.worktrees)]
        for repo in repos:
            make_repo(repo)
        sessions = [
            Session(
                payload=session_json(n, repos[n % len(repos)]),
                offset=args.interval * n / args.sessions,
            )
            for n in range(args.sessions)
        ]

        env = command_env()
        p2 = probe_pid()
        usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.monotonic()
        end = start + args.seconds
        threads = [
            threading.Thread(
                target=run_session, args=(s, args.command, env, start, end, args.interval)
            )
            for s in sessions
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.monotonic() - start
        usage1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        p3 = probe_pid()

    walls = [w for s in sessions for w in s.walls]
    redraws = len(walls)
    user = usage1.ru_utime - usage0.ru_utime
    system = usage1.ru_stime - usage0.ru_stime
    machine = pid_advance(p2, p3)
    starts = max(0.0, machine - idle_rate * wall)
    errors = [s.error for s in sessions if s.error]

    def ms(value: float) -> float:
        return round(value * 1000, 1)

    return {
        "command": args.command.replace(str(Path.home()), "~"),
        "sessions": args.sessions,
        "worktrees": args.worktrees,
        "seconds": args.seconds,
        "interval": args.interval,
        "wall_seconds": round(wall, 2),
        "redraws": redraws,
        "failures": sum(s.failures for s in sessions),
        "skipped_ticks": sum(s.skipped for s in sessions),
        "first_error": errors[0] if errors else None,
        "redraw_wall_ms": {
            "median": ms(statistics.median(walls)) if walls else None,
            "p95": ms(percentile(walls, 0.95)) if walls else None,
            "max": ms(max(walls)) if walls else None,
        },
        "child_cpu": {
            "seconds": round(user + system, 2),
            "user": round(user, 2),
            "system": round(system, 2),
            "cores": round((user + system) / wall, 2),
        },
        "process_starts": {
            "approximate": True,
            "per_second": round(starts / wall, 1),
            "per_redraw": round(starts / redraws, 1) if redraws else None,
            "idle_per_second": round(idle_rate, 1),
            "machine_per_second": round(machine / wall, 1),
        },
    }


def human(r: dict) -> str:
    w, cpu, ps = r["redraw_wall_ms"], r["child_cpu"], r["process_starts"]
    lines = [
        f"Statusline benchmark: {r['sessions']} sessions over {r['worktrees']} worktrees,"
        f" {r['wall_seconds']} s, every {r['interval']} s",
        f"Command: {r['command']}",
        f"Redraws: {r['redraws']} ({r['failures']} failed, {r['skipped_ticks']} skipped ticks)",
    ]
    if r["redraws"]:
        lines.append(f"Redraw wall: median {w['median']} ms, p95 {w['p95']} ms, max {w['max']} ms")
    lines += [
        f"Child CPU: {cpu['seconds']} s (user {cpu['user']}, system {cpu['system']})"
        f" = {cpu['cores']} cores",
        f"Process starts (approximate): {ps['per_second']}/s, {ps['per_redraw']} per redraw"
        f" ({ps['machine_per_second']}/s machine-wide, idle baseline"
        f" {ps['idle_per_second']}/s subtracted)",
    ]
    if r["first_error"]:
        lines.append(f"First error: {r['first_error']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", help="statusline command, run as `sh -c <command>`")
    parser.add_argument("--sessions", type=int, default=24)
    parser.add_argument("--worktrees", type=int, default=4)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument(
        "--baseline",
        type=float,
        default=5.0,
        help="idle seconds measured first (capped at --seconds)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()
    if min(args.sessions, args.worktrees) < 1 or min(args.seconds, args.interval) <= 0:
        parser.error("--sessions and --worktrees must be at least 1, times positive")

    report = bench(args)
    print(json.dumps(report, indent=2) if args.json else human(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
