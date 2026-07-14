"""Result models shared by the checker and command-line interface."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    path: str = ""
    line: int | None = None
    severity: str = "error"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckResult:
    root: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(item.severity == "error" for item in self.diagnostics)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.diagnostics)

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "root": self.root,
            "summary": {
                "passed": self.passed,
                "errors": self.error_count,
                "warnings": self.warning_count,
            },
            "stats": dict(sorted(self.stats.items())),
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }
