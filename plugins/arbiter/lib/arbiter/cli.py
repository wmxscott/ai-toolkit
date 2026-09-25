"""Argument parsing and dispatch."""

import argparse

from . import __doc__ as package_doc
from . import __version__, commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arbiter",
        description=(package_doc or "").strip().split("\n")[0],
    )
    parser.add_argument("--version", action="version", version=f"arbiter {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run gates against the current change set")
    run.add_argument("--task", help="run only this task")
    run.add_argument("--no-cache", action="store_true", help="ignore cached verdicts")
    run.set_defaults(handler=commands.run)

    init = sub.add_parser("init", help="copy a template into this repository")
    init.add_argument("template", nargs="?", help="template name; omit to list what is available")
    init.add_argument("--force", action="store_true", help="overwrite an existing arbiter.toml")
    init.set_defaults(handler=commands.init)

    sub.add_parser("hook", help="Stop-hook entry point; reads hook JSON on stdin").set_defaults(
        handler=commands.hook
    )
    sub.add_parser("plan", help="show what would run and why, without running it").set_defaults(
        handler=commands.plan
    )
    sub.add_parser("status", help="cached verdicts for the current change set").set_defaults(
        handler=commands.status
    )
    sub.add_parser("clean", help="clear cache and scratch").set_defaults(handler=commands.clean)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)
