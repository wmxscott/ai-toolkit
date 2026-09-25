"""Rendering verdicts for a terminal or for the agent."""

from .verdicts import Verdict

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"


class Reporter:
    """Formats verdicts. Colour is suppressed when writing to the agent."""

    def __init__(self, color: bool = False):
        self.color = color

    def paint(self, code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if self.color else text

    def _mark(self, verdict: Verdict) -> str:
        if verdict.ok:
            return self.paint(GREEN, "PASS")
        if not verdict.task.required:
            return self.paint(YELLOW, "WARN")
        return self.paint(RED, "FAIL")

    def render(self, verdicts: list[Verdict]) -> str:
        lines: list[str] = []
        for verdict in verdicts:
            suffix = self.paint(DIM, " (cached)") if verdict.cached else ""
            lines.append(
                f"  {self._mark(verdict)}  {verdict.task.name}{suffix}  "
                f"{self.paint(DIM, verdict.summary)}"
            )
            if verdict.ok:
                continue
            for finding in verdict.findings[:20]:
                if not finding.issue:
                    continue
                head = " ".join(x for x in (finding.severity, finding.location) if x)
                prefix = f"        - {head}: " if head else "        - "
                lines.append(prefix + finding.issue)
        return "\n".join(lines)
