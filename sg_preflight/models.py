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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Finding":
        return cls(
            pack=str(payload.get("pack", "")),
            code=str(payload.get("code", "")),
            severity=str(payload.get("severity", "")),
            message=str(payload.get("message", "")),
            location=payload.get("location"),
            details=dict(payload.get("details", {}))
            if isinstance(payload.get("details"), dict)
            else {},
        )


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PackResult":
        findings = payload.get("findings", [])
        return cls(
            pack=str(payload.get("pack", "")),
            findings=[
                Finding.from_dict(item)
                for item in findings
                if isinstance(item, dict)
            ],
        )


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Report":
        return cls(
            bundle=str(payload.get("bundle", "")),
            context=dict(payload.get("context", {}))
            if isinstance(payload.get("context"), dict)
            else {},
            packs=[
                PackResult.from_dict(item)
                for item in payload.get("packs", [])
                if isinstance(item, dict)
            ],
        )

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
