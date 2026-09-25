"""arbiter — declarative quality gates that hold a coding agent's turn open.

Projects declare gates in TOML. Deterministic gates are shell commands; judge
gates are LLM reviews run as isolated subprocesses that can read the repository
and write scratch files but cannot modify the code under review.

Design notes: docs/design.md in the plugin.
"""

__version__ = "0.1.0"
