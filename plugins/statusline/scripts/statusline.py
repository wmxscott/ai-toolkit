#!/usr/bin/env python3
"""Three-line Claude Code statusline for NerdFont, true-colour terminals.

Reads the statusline JSON on stdin and prints:
  1. vim mode, git repo and path, branch, lines added and removed
  2. model, effort, output style, context window usage
  3. rate-limit reset, cost, session usage, weekly usage
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def rgb(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


@dataclass(frozen=True)
class Palette:
    lavender: str
    sky: str
    mint: str
    gold: str
    coral: str
    rose: str
    silver: str
    muted: str
    bar_ok: str
    bar_warn: str
    bar_crit: str
    vim_normal: str
    vim_insert: str
    vim_visual: str
    vim_command: str
    effort_low: str
    effort_max: str


# Catppuccin Macchiato
DARK = Palette(
    lavender=rgb(183, 189, 248),
    sky=rgb(145, 215, 227),
    mint=rgb(166, 218, 149),
    gold=rgb(238, 212, 159),
    coral=rgb(245, 169, 127),
    rose=rgb(238, 153, 160),
    silver=rgb(165, 173, 203),
    muted=rgb(110, 115, 141),
    bar_ok=rgb(139, 213, 202),
    bar_warn=rgb(238, 212, 159),
    bar_crit=rgb(237, 135, 150),
    vim_normal=rgb(138, 173, 244),
    vim_insert=rgb(166, 218, 149),
    vim_visual=rgb(198, 160, 246),
    vim_command=rgb(237, 135, 150),
    effort_low=rgb(125, 196, 228),
    effort_max=rgb(237, 135, 150),
)

# Catppuccin Latte
LIGHT = Palette(
    lavender=rgb(114, 135, 253),
    sky=rgb(4, 165, 229),
    mint=rgb(64, 160, 43),
    gold=rgb(223, 142, 29),
    coral=rgb(254, 100, 11),
    rose=rgb(230, 69, 83),
    silver=rgb(108, 111, 133),
    muted=rgb(140, 143, 161),
    bar_ok=rgb(23, 146, 153),
    bar_warn=rgb(223, 142, 29),
    bar_crit=rgb(210, 15, 57),
    vim_normal=rgb(30, 102, 245),
    vim_insert=rgb(64, 160, 43),
    vim_visual=rgb(136, 57, 239),
    vim_command=rgb(210, 15, 57),
    effort_low=rgb(32, 159, 181),
    effort_max=rgb(210, 15, 57),
)

PALETTES = {"dark": DARK, "light": LIGHT}

ICO_MODEL = "\uf135"
ICO_BOLT = "\uf0e7"
ICO_DB = "\ue64d"
ICO_CLOCK = "\U000f13ab"
ICO_DOLLAR = "\uf252"
ICO_CAL = "\U000f1a32"
ICO_VIM = "\ue62b"
ICO_GIT = "\ueafc"
ICO_BRANCH = "\ue725"
ICO_STYLE = "\U000f150f"

EM_DASH = "\u2014"

CIRCLES = ("\u25ef", "\u25d4", "\u25d1", "\u25d5", "\u25cf")

EFFORTS = {
    "low": ("\u2581 low", "effort_low"),
    "medium": ("\u2582 med", "gold"),
    "high": ("\u2583 high", "coral"),
    "xhigh": ("\u2585 xhigh", "rose"),
    "max": ("\u2588 max", "effort_max"),
}

VIM_MODES = {
    "NORMAL": "vim_normal",
    "INSERT": "vim_insert",
    "VISUAL": "vim_visual",
    "V-LINE": "vim_visual",
    "V-BLOCK": "vim_visual",
    "COMMAND": "vim_command",
    "REPLACE": "coral",
}

MODEL_PREFIXES = (("Claude Opus", "Opus"), ("Claude Sonnet", "Sonnet"), ("Claude Haiku", "Haiku"))

# Skip huge untracked files when counting added lines; they are almost never source.
MAX_UNTRACKED_BYTES = 10 * 1024 * 1024


def trigger_file() -> str:
    return os.path.expanduser("~/.local/share/theme-monitor/theme-change.trigger")


def macos_appearance() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # The key only exists in dark mode, so a failed read means light.
    return "dark" if result.returncode == 0 and result.stdout.strip() == "Dark" else "light"


def detect_theme() -> str:
    override = os.environ.get("CLAUDE_STATUSLINE_THEME", "").strip().lower()
    if override in PALETTES:
        return override
    try:
        with open(trigger_file()) as f:
            value = f.read().strip().lower()
        if value in PALETTES:
            return value
    except OSError:
        pass
    return macos_appearance() or "dark"


def get(d: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def pct_color(p: Palette, pct: float) -> str:
    return p.bar_ok if pct < 60 else (p.bar_warn if pct < 85 else p.bar_crit)


def progress_circle(p: Palette, pct: float) -> str:
    idx = max(0, min(len(CIRCLES) - 1, round(pct / 100 * (len(CIRCLES) - 1))))
    return f"{pct_color(p, pct)}{CIRCLES[idx]}{RESET}"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def fmt_cost(usd: float) -> str:
    if usd < 0.001:
        return "$0"
    if usd < 1.0:
        return f"${usd:.3f}"
    return f"${usd:.2f}"


def fmt_duration(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def fmt_resets(value: object, now: datetime | None = None) -> str:
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value >= 1e10 else value
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        sec = int((dt - (now or datetime.now(timezone.utc))).total_seconds())
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"
    if sec <= 0:
        return "now"
    h, rest = divmod(sec, 3600)
    m = rest // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _git(cwd: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            # Refreshing every second must not contend for the index lock.
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _count_lines(root: str, names: list[str]) -> int:
    total = 0
    for name in names:
        path = os.path.join(root, name)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) > MAX_UNTRACKED_BYTES:
                continue
            with open(path, "rb") as f:
                total += f.read().count(b"\n")
        except OSError:
            continue
    return total


def git_info(cwd: str) -> dict | None:
    root = _git(cwd, "rev-parse", "--show-toplevel")
    if not root:
        return None
    branch = _git(cwd, "branch", "--show-current") or _git(cwd, "rev-parse", "--short", "HEAD")
    stat = _git(root, "diff", "--shortstat", "HEAD")
    added = re.search(r"(\d+) insertion", stat)
    deleted = re.search(r"(\d+) deletion", stat)
    untracked = _git(root, "ls-files", "-z", "--others", "--exclude-standard")
    return {
        "repo": os.path.basename(root),
        "branch": branch,
        "rel": _git(cwd, "rev-parse", "--show-prefix").rstrip("/"),
        "added": (int(added.group(1)) if added else 0)
        + _count_lines(root, [n for n in untracked.split("\0") if n]),
        "deleted": int(deleted.group(1)) if deleted else 0,
    }


def sep(p: Palette) -> str:
    return f"  {p.muted}\u00b7{RESET}  "


def vim_badge(p: Palette, mode: str) -> str:
    m = mode.upper()
    col = getattr(p, VIM_MODES.get(m, "silver"))
    return f"{BOLD}{col}{ICO_VIM} {m}{RESET}"


def effort_badge(p: Palette, level: str) -> str:
    label, attr = EFFORTS.get(level, (level, "silver"))
    return f"{BOLD}{getattr(p, attr)}{ICO_BOLT} {label}{RESET}"


def line1(d: dict, p: Palette) -> str:
    cwd = get(d, "workspace", "current_dir") or get(d, "cwd") or os.getcwd()
    parts: list[str] = []

    mode = get(d, "vim", "mode")
    if isinstance(mode, str) and mode:
        parts.append(vim_badge(p, mode))

    gi = git_info(str(cwd))
    if gi:
        repo = f"{BOLD}{p.lavender}{gi['repo']}{RESET}"
        if gi["rel"]:
            repo += f"{p.muted}/{gi['rel']}{RESET}"
        parts.append(f"{BOLD}{p.lavender}{ICO_GIT} {RESET}{repo}")
        if gi["branch"]:
            parts.append(f"{p.gold}{ICO_BRANCH} {gi['branch']}{RESET}")
        changes = []
        if gi["added"]:
            changes.append(f"{p.mint}+{gi['added']}{RESET}")
        if gi["deleted"]:
            changes.append(f"{p.bar_crit}-{gi['deleted']}{RESET}")
        if changes:
            parts.append(" ".join(changes))
    else:
        path = str(cwd)
        home = os.path.expanduser("~")
        if path == home or path.startswith(home + os.sep):
            path = "~" + path[len(home) :]
        parts.append(f"{p.silver}{path}{RESET}")

    return sep(p).join(parts)


def line2(d: dict, p: Palette) -> str:
    name = get(d, "model", "display_name")
    name = name if isinstance(name, str) else ""
    for long, short in MODEL_PREFIXES:
        name = name.replace(long, short)
    model = f"{BOLD}{p.lavender}{ICO_MODEL} {name or EM_DASH}{RESET}"

    inner = []
    level = get(d, "effort", "level")
    if isinstance(level, str) and level:
        inner.append(effort_badge(p, level))
    style = get(d, "output_style", "name")
    if isinstance(style, str) and style and style.lower() != "default":
        inner.append(f"{p.sky}{ICO_STYLE} {style}{RESET}")
    modes = f"{p.muted} | {RESET}".join(inner)

    pct = number(get(d, "context_window", "used_percentage")) or 0.0
    total = int(number(get(d, "context_window", "context_window_size")) or 0)
    col = pct_color(p, pct)
    ctx = f"{col}{ICO_DB}{RESET} {progress_circle(p, pct)} {BOLD}{col}{pct:.0f}%{RESET}"
    if total:
        used = int(pct / 100 * total)
        ctx += f"  {DIM}({fmt_tokens(used)}/{fmt_tokens(total)}){RESET}"

    return sep(p).join(x for x in (model, modes, ctx) if x)


def line3(d: dict, p: Palette) -> str:
    parts: list[str] = []

    resets = get(d, "rate_limits", "five_hour", "resets_at")
    if resets:
        parts.append(f"{p.sky}{ICO_CLOCK} {fmt_resets(resets)}{RESET}")

    usd = number(get(d, "cost", "total_cost_usd"))
    session = number(get(d, "rate_limits", "five_hour", "used_percentage"))
    if usd is not None and usd > 0:
        s = f"{p.mint}{ICO_DOLLAR} {fmt_cost(usd)}{RESET}"
        if session is not None:
            s += f"  {pct_color(p, session)}{session:.0f}% session{RESET}"
        parts.append(s)
    elif session is not None:
        parts.append(f"{pct_color(p, session)}{ICO_DOLLAR} {session:.0f}% session{RESET}")

    weekly = number(get(d, "rate_limits", "seven_day", "used_percentage"))
    if weekly is not None:
        parts.append(f"{pct_color(p, weekly)}{ICO_CAL}  {weekly:.0f}% weekly{RESET}")

    if not parts:
        ms = number(get(d, "cost", "total_duration_ms"))
        if ms:
            parts.append(f"{p.sky}{ICO_CLOCK} {fmt_duration(int(ms / 1000))}{RESET}")

    return sep(p).join(parts)


def render(data: dict, theme: str) -> str:
    p = PALETTES[theme]
    out = []
    for fn in (line1, line2, line3):
        try:
            line = fn(data, p)
        except Exception as exc:
            line = f"{p.bar_crit}statusline error: {exc}{RESET}"
        if line:
            out.append(line)
    return "\n".join(out) + "\n"


def main() -> None:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    sys.stdout.write(render(data, detect_theme()))


if __name__ == "__main__":
    main()
