from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from sg_preflight.delivery_readiness import DeliveryReadinessEntry, build_delivery_readiness_board
from sg_preflight.io_utils import read_text as _read_text


CONFIG_RELATIVE_PATH = Path("export") / "tests" / "test_config.lua"
BASELINE_TMP_FILENAME = "test_config_tmp.lua"
CAUTIOUS_BASELINE_LABEL = "not found in discovered baseline evidence"
EVIDENCE_ONLY_BANNER = (
    "Evidence only - disabled-test coverage is a local inventory; manual review remains required."
)

_CALL_RE = re.compile(
    r"\b(?P<function>disableTest|addTest|addInterfaceTest|addRLogicView|addTest_[A-Za-z0-9_]+)"
    r"\s*\(\s*(?P<quote>[\"'])(?P<name>.*?)(?P=quote)",
    re.DOTALL,
)


@dataclass(frozen=True)
class LuaTestCall:
    function: str
    name: str
    line_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "name": self.name,
            "line_number": self.line_number,
        }


@dataclass(frozen=True)
class BaselineEvidence:
    state: str
    source_paths: tuple[str, ...]
    test_names: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return bool(self.test_names)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "source_paths": list(self.source_paths),
            "test_count": len(self.test_names),
            "test_names": list(self.test_names),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DisabledTestsEntry:
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    config_path: str
    has_config: bool
    config_status: str
    disabled_tests: tuple[LuaTestCall, ...] = ()
    added_tests: tuple[LuaTestCall, ...] = ()
    commented_call_count: int = 0
    duplicate_disabled_tests: tuple[str, ...] = ()
    baseline_review_disabled_tests: tuple[str, ...] = ()

    @property
    def disabled_count(self) -> int:
        return len(self.disabled_tests)

    @property
    def added_count(self) -> int:
        return len(self.added_tests)

    @property
    def needs_review(self) -> bool:
        return bool(self.duplicate_disabled_tests or self.baseline_review_disabled_tests)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "config_path": self.config_path,
            "has_config": self.has_config,
            "config_status": self.config_status,
            "disabled_count": self.disabled_count,
            "added_count": self.added_count,
            "commented_call_count": self.commented_call_count,
            "duplicate_disabled_tests": list(self.duplicate_disabled_tests),
            "baseline_review_disabled_tests": list(self.baseline_review_disabled_tests),
            "disabled_tests": [call.to_dict() for call in self.disabled_tests],
            "added_tests": [call.to_dict() for call in self.added_tests],
            "needs_review": self.needs_review,
        }


@dataclass(frozen=True)
class DisabledTestsBoard:
    repo_root: Path
    source_state: str
    generated_at_utc: str
    entries: tuple[DisabledTestsEntry, ...]
    baseline: BaselineEvidence
    manual_review_banner: str = EVIDENCE_ONLY_BANNER

    @property
    def counts(self) -> dict[str, int]:
        configured = sum(1 for entry in self.entries if entry.has_config)
        no_config = len(self.entries) - configured
        return {
            "total": len(self.entries),
            "configured": configured,
            "no_config": no_config,
            "disabled_call_total": sum(entry.disabled_count for entry in self.entries),
            "disabled_unique_total": len({call.name for entry in self.entries for call in entry.disabled_tests}),
            "added_call_total": sum(entry.added_count for entry in self.entries),
            "added_unique_total": len({call.name for entry in self.entries for call in entry.added_tests}),
            "duplicate_entry_count": sum(1 for entry in self.entries if entry.duplicate_disabled_tests),
            "baseline_review_entry_count": sum(1 for entry in self.entries if entry.baseline_review_disabled_tests),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repo_root": str(self.repo_root),
            "source_state": self.source_state,
            "generated_at_utc": self.generated_at_utc,
            "manual_review_banner": self.manual_review_banner,
            "cautious_baseline_label": CAUTIOUS_BASELINE_LABEL,
            "counts": self.counts,
            "baseline": self.baseline.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
        }


def strip_lua_comments(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string: str | None = None
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string is not None:
            output.append(char)
            if char == "\\" and index + 1 < len(text):
                output.append(text[index + 1])
                index += 2
                continue
            if char == in_string:
                in_string = None
            index += 1
            continue
        if char in {"'", '"'}:
            in_string = char
            output.append(char)
            index += 1
            continue
        if char == "-" and next_char == "-":
            if index + 3 < len(text) and text[index + 2 : index + 4] == "[[":
                end_index = text.find("]]", index + 4)
                if end_index == -1:
                    output.append("\n" * text[index:].count("\n"))
                    break
                block = text[index : end_index + 2]
                output.append("\n" * block.count("\n"))
                index = end_index + 2
                continue
            end_index = text.find("\n", index)
            if end_index == -1:
                break
            output.append("\n")
            index = end_index + 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def extract_lua_test_calls(text: str) -> tuple[LuaTestCall, ...]:
    stripped = strip_lua_comments(text)
    calls: list[LuaTestCall] = []
    for match in _CALL_RE.finditer(stripped):
        calls.append(
            LuaTestCall(
                function=match.group("function"),
                name=match.group("name"),
                line_number=stripped.count("\n", 0, match.start()) + 1,
            )
        )
    return tuple(calls)


def _raw_call_count(text: str) -> int:
    return len(tuple(_CALL_RE.finditer(text)))


def _baseline_from_tmp(path: Path) -> tuple[str, ...]:
    calls = extract_lua_test_calls(_read_text(path))
    first_disable_line = min((call.line_number for call in calls if call.function == "disableTest"), default=10**9)
    return tuple(
        call.name
        for call in calls
        if call.function in {"addTest", "addInterfaceTest"} and call.line_number < first_disable_line
    )


def _expected_screenshot_names(entries: tuple[DeliveryReadinessEntry, ...], repo_root: Path) -> tuple[str, ...]:
    names: set[str] = set()
    for entry in entries:
        expected_root = repo_root / Path(entry.relative_path) / "export" / "tests" / "expected"
        if expected_root.is_dir():
            names.update(path.stem for path in expected_root.glob("*.png") if path.is_file())
    return tuple(sorted(names))


def discover_baseline_evidence(
    repo_root: Path,
    entries: tuple[DeliveryReadinessEntry, ...],
) -> BaselineEvidence:
    names: set[str] = set()
    source_paths: list[str] = []
    notes: list[str] = []
    for path in sorted(repo_root.rglob(BASELINE_TMP_FILENAME)):
        if not path.is_file():
            continue
        baseline_names = _baseline_from_tmp(path)
        if baseline_names:
            names.update(baseline_names)
            source_paths.append(str(path))
    expected_names = _expected_screenshot_names(entries, repo_root)
    if expected_names:
        names.update(expected_names)
        source_paths.append("export/tests/expected/*.png")
    if not names:
        notes.append("No generated baseline or expected screenshot names were found; review flags are suppressed.")
        return BaselineEvidence(state="missing", source_paths=tuple(source_paths), test_names=(), notes=tuple(notes))
    return BaselineEvidence(
        state="available",
        source_paths=tuple(dict.fromkeys(source_paths)),
        test_names=tuple(sorted(names)),
        notes=tuple(notes),
    )


def _entry_config_path(repo_root: Path, entry: DeliveryReadinessEntry) -> Path:
    return repo_root / Path(entry.relative_path) / CONFIG_RELATIVE_PATH


def _build_entry(
    repo_root: Path,
    delivery_entry: DeliveryReadinessEntry,
    baseline_names: set[str],
) -> DisabledTestsEntry:
    config_path = _entry_config_path(repo_root, delivery_entry)
    if not config_path.is_file():
        return DisabledTestsEntry(
            source_root=delivery_entry.source_root,
            brand=delivery_entry.brand,
            model_id=delivery_entry.model_id,
            relative_path=delivery_entry.relative_path,
            config_path=str(config_path),
            has_config=False,
            config_status="no_config",
        )

    text = _read_text(config_path)
    calls = extract_lua_test_calls(text)
    disabled = tuple(call for call in calls if call.function == "disableTest")
    added = tuple(call for call in calls if call.function == "addTest")
    disabled_counts = Counter(call.name for call in disabled)
    duplicates = tuple(sorted(name for name, count in disabled_counts.items() if count > 1))
    baseline_review = (
        tuple(sorted({call.name for call in disabled if call.name not in baseline_names}))
        if baseline_names
        else ()
    )
    raw_count = _raw_call_count(text)
    active_count = len(calls)
    return DisabledTestsEntry(
        source_root=delivery_entry.source_root,
        brand=delivery_entry.brand,
        model_id=delivery_entry.model_id,
        relative_path=delivery_entry.relative_path,
        config_path=str(config_path),
        has_config=True,
        config_status="configured",
        disabled_tests=disabled,
        added_tests=added,
        commented_call_count=max(0, raw_count - active_count),
        duplicate_disabled_tests=duplicates,
        baseline_review_disabled_tests=baseline_review,
    )


def build_disabled_tests_board(
    repo_root: Path | None = None,
    *,
    workspace_root: Path | None = None,
    bmw_repo_root: Path | None = None,
) -> DisabledTestsBoard:
    delivery_board = build_delivery_readiness_board(
        repo_root,
        workspace_root=workspace_root,
        bmw_repo_root=bmw_repo_root,
    )
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if delivery_board.source_state != "ready":
        return DisabledTestsBoard(
            repo_root=delivery_board.repo_root,
            source_state=delivery_board.source_state,
            generated_at_utc=generated_at,
            entries=(),
            baseline=BaselineEvidence(state="missing", source_paths=(), test_names=()),
        )
    baseline = discover_baseline_evidence(delivery_board.repo_root, delivery_board.entries)
    baseline_names = set(baseline.test_names)
    entries = tuple(
        _build_entry(delivery_board.repo_root, entry, baseline_names)
        for entry in delivery_board.entries
    )
    return DisabledTestsBoard(
        repo_root=delivery_board.repo_root,
        source_state=delivery_board.source_state,
        generated_at_utc=generated_at,
        entries=entries,
        baseline=baseline,
    )


def disabled_tests_markdown(board: DisabledTestsBoard) -> str:
    payload = board.to_dict()
    counts = payload["counts"]
    baseline = payload["baseline"]
    lines = [
        "# Disabled-Test Coverage",
        "",
        EVIDENCE_ONLY_BANNER,
        "",
        f"- source: `{payload['repo_root']}`",
        f"- generated: `{payload['generated_at_utc']}`",
        f"- total cars: {counts['total']}",
        f"- configured: {counts['configured']}",
        f"- no config: {counts['no_config']}",
        f"- disabled calls: {counts['disabled_call_total']}",
        f"- added calls: {counts['added_call_total']}",
        f"- duplicate-disable rows: {counts['duplicate_entry_count']}",
        f"- baseline-review rows: {counts['baseline_review_entry_count']}",
        f"- baseline evidence: {baseline['state']} ({baseline['test_count']} names)",
        "",
        "| Source | Brand | Model | Config | Disabled | Added | Review flags |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for entry in board.entries:
        flags = []
        if entry.duplicate_disabled_tests:
            flags.append("duplicates: " + ", ".join(entry.duplicate_disabled_tests))
        if entry.baseline_review_disabled_tests:
            flags.append(
                CAUTIOUS_BASELINE_LABEL + ": " + ", ".join(entry.baseline_review_disabled_tests)
            )
        lines.append(
            "| "
            + " | ".join(
                (
                    entry.source_root,
                    entry.brand,
                    entry.model_id,
                    entry.config_status,
                    str(entry.disabled_count),
                    str(entry.added_count),
                    "; ".join(flags).replace("|", "\\|"),
                )
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def write_disabled_tests_board(board: DisabledTestsBoard, output_root: Path) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "disabled-tests.json"
    markdown_path = output_root / "disabled-tests.md"
    json_path.write_text(json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(disabled_tests_markdown(board), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
