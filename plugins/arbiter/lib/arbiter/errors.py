"""Exception types.

Configuration problems are always fatal. A gate framework that silently skips a
misconfigured gate is worse than one that refuses to run, because the failure
mode is an unguarded turn that looks guarded.
"""


class ArbiterError(Exception):
    """Base class for every error arbiter raises deliberately."""


class ConfigError(ArbiterError):
    """Malformed configuration. Never fails open."""
