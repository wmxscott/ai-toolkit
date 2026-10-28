"""Record statusline.py's output on fixed inputs as golden files for the Go port.

Usage: uv run python plugins/statusline/tests/gen_golden.py [--check]
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
TESTDATA = PLUGIN / "testdata"
GOLDEN = TESTDATA / "golden"
CONSTANTS = TESTDATA / "constants.json"

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
T = int(NOW.timestamp())
HOME = "/home/user"
PROCESS_CWD = f"{HOME}/nowhere"
PROJECT = f"{HOME}/src/project"
THEMES = ("dark", "light")

SAMPLE = {
    "cwd": PROJECT,
    "workspace": {"current_dir": PROJECT},
    "model": {"id": "claude-opus-4-7", "display_name": "Claude Opus 4.7"},
    "vim": {"mode": "insert"},
    "effort": {"level": "high"},
    "output_style": {"name": "Explanatory"},
    "context_window": {"used_percentage": 42, "context_window_size": 200000},
    "cost": {"total_cost_usd": 1.234, "total_duration_ms": 125000},
    "rate_limits": {
        "five_hour": {"used_percentage": 23.5, "resets_at": T + 2 * 3600 + 14 * 60 + 30},
        "seven_day": {"used_percentage": 41.2, "resets_at": T + 5 * 86400},
    },
}


DROP = object()


def variant(**changes: object) -> dict:
    """SAMPLE with dotted keys replaced, or removed when the value is DROP."""
    data = copy.deepcopy(SAMPLE)
    for dotted, value in changes.items():
        *parents, last = dotted.split("__")
        node = data
        for key in parents:
            node = node.setdefault(key, {})
        if value is DROP:
            node.pop(last, None)
        else:
            node[last] = value
    return data


def limits(five: object = DROP, seven: object = DROP, resets: object = DROP) -> dict:
    out: dict = {}
    if five is not DROP or resets is not DROP:
        out["five_hour"] = {}
        if five is not DROP:
            out["five_hour"]["used_percentage"] = five
        if resets is not DROP:
            out["five_hour"]["resets_at"] = resets
    if seven is not DROP:
        out["seven_day"] = {"used_percentage": seven, "resets_at": T + 86400}
    return out


CASES: dict[str, dict] = {
    "sample": SAMPLE,
    "empty": {},
    "minimal": {"cwd": PROJECT},
    "vim-normal-effort-low": variant(vim__mode="NORMAL", effort__level="low"),
    "vim-visual-effort-medium": variant(vim__mode="visual", effort__level="medium"),
    "vim-v-line-effort-xhigh": variant(vim__mode="V-LINE", effort__level="xhigh"),
    "vim-v-block-effort-max": variant(vim__mode="V-BLOCK", effort__level="max"),
    "vim-command-effort-unknown": variant(vim__mode="command", effort__level="turbo"),
    "vim-replace-no-effort": variant(vim__mode="REPLACE", effort=DROP),
    "vim-unknown-empty-effort": variant(vim__mode="weird", effort__level=""),
    "style-default": variant(output_style__name="default", vim=DROP),
    "style-default-capitalised": variant(output_style__name="Default"),
    "style-only": variant(effort=DROP, output_style__name="Learning"),
    "context-0": variant(context_window__used_percentage=0),
    "context-59": variant(context_window__used_percentage=59),
    "context-60": variant(context_window__used_percentage=60),
    "context-84": variant(context_window__used_percentage=84.4),
    "context-85": variant(context_window__used_percentage=85),
    "context-100": variant(context_window__used_percentage=100),
    "context-no-window": variant(context_window={"used_percentage": 37.5}),
    "context-half-even": {
        "cwd": PROJECT,
        "context_window": {"used_percentage": 62.5, "context_window_size": 1000000},
    },
    "context-tokens-small": variant(context_window__used_percentage=0.4995),
    "context-negative": variant(context_window__used_percentage=-0.4),
    "cost-tiny": variant(cost__total_cost_usd=0.0005, rate_limits=DROP),
    "cost-small": variant(cost__total_cost_usd=0.0421, rate_limits=DROP),
    "cost-half-way": variant(cost__total_cost_usd=2.675),
    "cost-zero-with-limits": variant(cost__total_cost_usd=0),
    "limits-five-hour-only": variant(rate_limits=limits(five=23.5, resets=T + 3600)),
    "limits-seven-day-only": variant(rate_limits=limits(seven=41.2)),
    "limits-critical": variant(rate_limits=limits(five=90, seven=70, resets=T + 600)),
    "resets-ms": variant(rate_limits=limits(five=10, resets=(T + 45 * 60) * 1000)),
    "resets-iso-z": variant(rate_limits=limits(five=10, resets="2026-01-01T13:30:00Z")),
    "resets-iso-offset": variant(rate_limits=limits(five=10, resets="2026-01-01T15:05:30.5+02:00")),
    "resets-iso-naive": variant(rate_limits=limits(five=10, resets="2026-01-01T12:10:00")),
    "resets-past": variant(rate_limits=limits(five=10, resets=T - 60)),
    "resets-garbage": variant(rate_limits=limits(five=10, resets="soon")),
    "resets-numeric-string": variant(rate_limits=limits(five=10, resets=str(T + 600))),
    "resets-true": variant(rate_limits=limits(five=10, resets=True)),
    "resets-without-usage": variant(cost=DROP, rate_limits=limits(resets=T + 59)),
    "duration-fallback": {
        "cwd": PROJECT,
        "cost": {"total_cost_usd": 0, "total_duration_ms": 125000},
    },
    "duration-hours": {"cwd": PROJECT, "cost": {"total_duration_ms": 3 * 3600 * 1000 + 7 * 60000}},
    "duration-negative": {"cwd": PROJECT, "cost": {"total_duration_ms": -5000}},
    "model-sonnet": variant(model__display_name="Claude Sonnet 4.5"),
    "model-haiku": variant(model__display_name="Claude Haiku 4.5 (Claude Opus plan)"),
    "model-other": variant(model__display_name="GPT-5"),
    "model-not-a-string": variant(model__display_name=5),
    "numeric-strings": variant(
        context_window={"used_percentage": " 50 ", "context_window_size": "1000000"},
        cost__total_cost_usd="1.5",
        rate_limits=limits(five="23.5", seven="\t41.2\n"),
    ),
    "numeric-specials": variant(cost=DROP, rate_limits=limits(five="nan", seven="-Infinity")),
    "booleans": variant(
        context_window={"used_percentage": True, "context_window_size": True},
        cost={"total_cost_usd": True, "total_duration_ms": True},
        rate_limits=limits(five=False, seven=True),
    ),
    "nulls": {
        "cwd": PROJECT,
        "model": None,
        "vim": None,
        "context_window": None,
        "cost": None,
        "rate_limits": None,
    },
    "wrong-types": {
        "cwd": PROJECT,
        "workspace": [],
        "model": "x",
        "vim": [],
        "effort": {"level": None},
        "output_style": 3,
        "context_window": {"used_percentage": "n/a", "context_window_size": None},
        "cost": [],
        "rate_limits": {"five_hour": None, "seven_day": "x"},
    },
    "path-home": {"cwd": HOME},
    "path-outside-home": {"cwd": "/srv/data"},
    "path-home-prefix": {"cwd": f"{HOME}2/notes"},
    "path-workspace-over-cwd": {"cwd": "/srv/data", "workspace": {"current_dir": PROJECT}},
    "path-empty-workspace": {"cwd": "/srv/data", "workspace": {"current_dir": ""}},
    "path-unicode": {"cwd": f"{HOME}/café notes"},
}


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def load_statusline():
    spec = importlib.util.spec_from_file_location(
        "statusline", PLUGIN / "scripts" / "statusline.py"
    )
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules.
    sys.modules["statusline"] = module
    spec.loader.exec_module(module)
    module.datetime = FixedDatetime
    module.git_info = lambda cwd: None
    return module


def constants(sl) -> str:
    def palette(p) -> dict:
        return {name: getattr(p, name) for name in p.__dataclass_fields__}

    data = {
        "reset": sl.RESET,
        "bold": sl.BOLD,
        "dim": sl.DIM,
        "palettes": {name: palette(p) for name, p in sl.PALETTES.items()},
        "icons": {
            name.removeprefix("ICO_").lower(): value
            for name, value in vars(sl).items()
            if name.startswith("ICO_")
        },
        "em_dash": sl.EM_DASH,
        "circles": list(sl.CIRCLES),
        "efforts": {level: list(style) for level, style in sl.EFFORTS.items()},
        "vim_modes": sl.VIM_MODES,
        "model_prefixes": [list(pair) for pair in sl.MODEL_PREFIXES],
        "max_untracked_bytes": sl.MAX_UNTRACKED_BYTES,
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


README = f"""\
Golden output of `scripts/statusline.py`, written by `tests/gen_golden.py`. Do not edit by hand.

Each `<case>.json` is a statusline input; `<case>.dark.txt` and `<case>.light.txt` are the exact
stdout of `render(input, theme)`. They were recorded with:

- now: {NOW.isoformat().replace("+00:00", "Z")}
- HOME: {HOME}
- process working directory (inputs with no `workspace.current_dir` or `cwd`): {PROCESS_CWD}
- no git repository at any working directory (line 1 shows the path)
"""


def expected_files() -> dict[Path, str]:
    os.environ["HOME"] = HOME
    sl = load_statusline()
    files = {GOLDEN / "README.md": README, CONSTANTS: constants(sl)}
    with mock.patch.object(sl.os, "getcwd", return_value=PROCESS_CWD):
        for name, data in CASES.items():
            text = json.dumps(data, ensure_ascii=False) + "\n"
            files[GOLDEN / f"{name}.json"] = text
            for theme in THEMES:
                out = sl.render(json.loads(text), theme)
                if "statusline error" in out:
                    raise SystemExit(f"{name}: render raised, which the Go port doesn't emulate")
                files[GOLDEN / f"{name}.{theme}.txt"] = out
    return files


def on_disk() -> dict[Path, str]:
    paths = [*GOLDEN.glob("*"), CONSTANTS] if GOLDEN.is_dir() else [CONSTANTS]
    return {p: p.read_text(encoding="utf-8") for p in paths if p.is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the files are stale")
    args = parser.parse_args()

    want = expected_files()
    have = on_disk()
    if args.check:
        stale = sorted(
            str(p.relative_to(PLUGIN))
            for p in want.keys() | have.keys()
            if want.get(p) != have.get(p)
        )
        for path in stale:
            print(f"stale: {path}", file=sys.stderr)
        return 1 if stale else 0

    GOLDEN.mkdir(parents=True, exist_ok=True)
    for path in have.keys() - want.keys():
        path.unlink()
    for path, text in want.items():
        if have.get(path) != text:
            path.write_text(text, encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
