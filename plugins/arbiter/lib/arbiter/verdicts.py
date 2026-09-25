"""Verdict model and tolerant parsing of model output."""

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Task


@dataclass
class Finding:
    issue: str
    severity: str | None = None
    file: str | None = None
    line: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        line = data.get("line")
        return cls(
            issue=str(data.get("issue", "")).strip(),
            severity=data.get("severity"),
            file=data.get("file"),
            line=int(line) if isinstance(line, int) and line > 0 else None,
        )

    def to_dict(self) -> dict:
        return {
            "issue": self.issue,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
        }

    @property
    def location(self) -> str:
        if self.file and self.line:
            return f"{self.file}:{self.line}"
        return self.file or ""


@dataclass
class Verdict:
    """The outcome of one task."""

    task: "Task"
    ok: bool
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    cached: bool = False

    @property
    def blocks(self) -> bool:
        """Advisory tasks report their failure but never hold the turn."""
        return not self.ok and self.task.required

    def to_dict(self) -> dict:
        # Deliberately omits `required`: config is the source of truth for it,
        # and from_cache() rebuilds from the live Task. Persisting it would put
        # a stale value in front of anyone reading `arbiter status`.
        return {
            "ok": self.ok,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
        }

    @classmethod
    def from_cache(cls, task: "Task", data: dict) -> "Verdict":
        return cls(
            task=task,
            ok=bool(data.get("ok")),
            summary=data.get("summary", "cached"),
            findings=[Finding.from_dict(f) for f in data.get("findings") or []],
            cached=True,
        )

    @classmethod
    def failure(cls, task: "Task", summary: str, detail: str = "") -> "Verdict":
        findings = [Finding(issue=detail.strip())] if detail.strip() else []
        return cls(task=task, ok=False, summary=summary, findings=findings)

    @classmethod
    def from_payload(cls, task: "Task", payload: dict | None, fallback: str) -> "Verdict":
        if not payload or "ok" not in payload:
            return cls.failure(task, fallback)
        return cls(
            task=task,
            ok=bool(payload.get("ok")),
            summary=str(payload.get("summary", "")),
            findings=[Finding.from_dict(f) for f in payload.get("findings") or []],
        )


def extract_json(text: str) -> dict | None:
    """Pull a JSON object out of model output, fenced or bare.

    Models wrap structured output in prose or code fences often enough that
    strict parsing would fail on otherwise good verdicts.
    """
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
