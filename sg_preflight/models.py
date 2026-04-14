from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Finding:
    pack: str
    code: str
    severity: str
    message: str
    location: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackResult:
    pack: str
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity.lower() == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity.lower() == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity.lower() == "info")

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack": self.pack,
            "summary": {
                "errors": self.error_count,
                "warnings": self.warning_count,
                "info": self.info_count,
                "total": len(self.findings),
            },
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class Report:
    bundle: str
    context: dict[str, Any] = field(default_factory=dict)
    packs: list[PackResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle": self.bundle,
            "context": self.context,
            "summary": self.summary(),
            "packs": [p.to_dict() for p in self.packs],
        }

    def summary(self) -> dict[str, int]:
        errors = sum(p.error_count for p in self.packs)
        warnings = sum(p.warning_count for p in self.packs)
        info = sum(p.info_count for p in self.packs)
        return {
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "total": errors + warnings + info,
        }

    def has_threshold_or_worse(self, threshold: str) -> bool:
        threshold = threshold.lower()
        summary = self.summary()
        if threshold == "never":
            return False
        if threshold == "error":
            return summary["errors"] > 0
        if threshold == "warning":
            return (summary["errors"] + summary["warnings"]) > 0
        raise ValueError(f"Unsupported threshold: {threshold}")
