import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "scripts" / "bench_statusline.py"


def run_bench(tmp_path, command, *args):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(
        [sys.executable, str(BENCH), command, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_reports_shape_as_json(tmp_path):
    out = tmp_path / "inputs"
    command = f'cat >>"{out}"; echo >>"{out}"'
    result = run_bench(
        tmp_path, command, "--sessions", "2", "--worktrees", "2", "--seconds", "2", "--json"
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)

    assert report["sessions"] == 2
    assert report["worktrees"] == 2
    assert report["redraws"] >= 2
    assert report["failures"] == 0
    assert report["skipped_ticks"] >= 0
    wall = report["redraw_wall_ms"]
    assert 0 < wall["median"] <= wall["p95"]
    cpu = report["child_cpu"]
    assert cpu["seconds"] >= 0
    assert cpu["cores"] >= 0
    procs = report["process_starts"]
    assert procs["approximate"] is True
    assert {"per_second", "per_redraw", "idle_per_second"} <= procs.keys()

    inputs = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(inputs) == report["redraws"]
    dirs = {d["workspace"]["current_dir"] for d in inputs}
    assert len(dirs) == 2
    for d in inputs:
        assert d["cwd"] == d["workspace"]["current_dir"]
        assert d["model"]["display_name"]
        assert d["rate_limits"]["five_hour"]["resets_at"] > 0
        assert "used_percentage" in d["rate_limits"]["seven_day"]
    assert not any(Path(d).exists() for d in dirs)


def test_counts_failures(tmp_path):
    result = run_bench(tmp_path, "exit 3", "--sessions", "1", "--seconds", "1", "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["failures"] == report["redraws"] >= 1


def test_skips_ticks_while_a_redraw_runs(tmp_path):
    result = run_bench(
        tmp_path, "sleep 1.2", "--sessions", "1", "--seconds", "2", "--interval", "0.25", "--json"
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["redraws"] <= 2
    assert report["skipped_ticks"] >= 3


def test_prints_human_report(tmp_path):
    result = run_bench(tmp_path, "cat >/dev/null", "--sessions", "2", "--seconds", "1")
    assert result.returncode == 0, result.stderr
    for label in ("Redraw wall", "Child CPU", "cores", "Process starts", "approximate"):
        assert label in result.stdout


def test_undoes_pyenv_exec_for_the_command(tmp_path):
    root, prefix = tmp_path / "pyenv", tmp_path / "cellar"
    out = tmp_path / "env"
    shims = f"{root}/shims"
    added = [f"{root}/versions/3.13/bin", f"{prefix}/libexec", f"{root}/plugins/x/bin"]
    env = {
        "PATH": os.pathsep.join([*added, shims, os.environ["PATH"]]),
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "PYENV_ROOT": str(root),
        "PYENV_VERSION": "3.13",
        "PYENV_DIR": str(tmp_path),
        "_PYENV_INSTALL_PREFIX": str(prefix),
    }
    command = f'printf "%s\\n" "$PATH" "${{PYENV_VERSION-unset}}" >"{out}"'
    result = subprocess.run(
        [sys.executable, str(BENCH), command, "--sessions", "1", "--seconds", "0.5", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    path, version = out.read_text().splitlines()
    assert path == os.pathsep.join([shims, os.environ["PATH"]])
    assert version == "unset"
