"""Core data model shared by the engine, the CLI and the IDE."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

Origin = Literal["slang", "svguard"]


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    HINT = "hint"

    @property
    def rank(self) -> int:
        """0 is the most severe; used for sorting and --fail-on thresholds."""
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2, Severity.HINT: 3}


@dataclass(frozen=True, order=True)
class Location:
    """A span in a source file.

    Lines and columns are 1-based and counted in characters (not bytes), which is
    what editors use. The end is exclusive; when unknown it equals the start.
    """

    file: Path
    line: int
    col: int
    end_line: int
    end_col: int

    @classmethod
    def point(cls, file: Path, line: int, col: int) -> Location:
        return cls(file, line, col, line, col)


@dataclass(frozen=True)
class Finding:
    rule_id: str  # "SVG-C000", "SVG-S001", "SVG-U003" ...
    severity: Severity
    message: str  # one-line summary
    location: Location
    explain_id: str = ""  # explain/<id>.md; defaults to rule_id
    fix_hint: str | None = None
    origin: Origin = "svguard"
    slang_code: str | None = None  # e.g. "InferredLatch" when origin == "slang"

    def __post_init__(self) -> None:
        if not self.explain_id:
            object.__setattr__(self, "explain_id", self.rule_id)

    @property
    def sort_key(self) -> tuple[str, int, int, int, str]:
        loc = self.location
        return (str(loc.file), loc.line, loc.col, self.severity.rank, self.rule_id)

    def to_dict(self) -> dict[str, Any]:
        loc = self.location
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "message": self.message,
            "file": str(loc.file),
            "line": loc.line,
            "col": loc.col,
            "end_line": loc.end_line,
            "end_col": loc.end_col,
            "explain_id": self.explain_id,
            "fix_hint": self.fix_hint,
            "origin": self.origin,
            "slang_code": self.slang_code,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        location = Location(
            Path(data["file"]), data["line"], data["col"], data["end_line"], data["end_col"]
        )
        return cls(
            rule_id=data["rule_id"],
            severity=Severity(data["severity"]),
            message=data["message"],
            location=location,
            explain_id=data.get("explain_id", ""),
            fix_hint=data.get("fix_hint"),
            origin=data.get("origin", "svguard"),
            slang_code=data.get("slang_code"),
        )
