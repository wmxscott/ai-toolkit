"""Allows `python -m arbiter` alongside the bin wrapper."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
