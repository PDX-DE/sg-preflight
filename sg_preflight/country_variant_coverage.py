from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from sg_preflight.bmw_process import country_variant_lightfx_expectations
from sg_preflight.delivery_readiness import DeliveryReadinessEntry, build_delivery_readiness_board
from sg_preflight.disabled_tests import CONFIG_RELATIVE_PATH, strip_lua_comments


EVIDENCE_ONLY_BANNER = (
    "Evidence only - country-variant coverage is a local source and screenshot inventory; "
    "manual visual review remains required."
)
MISSING_EXPECTED_LABEL = "test defined but no expected baseline - review"
MAPPING_REVIEW_LABEL = "may not match the current country table - review"
NO_RUNTIME_LABEL = "no actual or diff screenshot captured locally"

_ADD_COUNTRY_TEST_RE = re.compile(
    r"\baddTest\s*\(\s*(?P<quote>[\"'])(?P<name>countryCoding[^\"']+)(?P=quote)(?P<body>.*?)(?=\n\s*(?:addTest|disableTest|addInterfaceTest|addRLogicView)\s*\(|\Z)",
    re.DOTALL,
)
_CONFIGURATION_RE = re.compile(r"\bconfiguration\s*\((?P<args>[^)]*)\)", re.DOTALL)
_COUNTRY_TABLE_ROW_RE = re.compile(r"^\|\s*(?P<id>\d+)\s*\|\s*(?P<country>[^|]+?)\s*\|", re.MULTILINE)
_LOGIC_COUNTRY_RE = re.compile(
    r"IN\.CountryVariant_ID\s*==\s*(?P<id>\d+)\s+then\s*\n\s*OUT\.(?P<country>[A-Za-z_]+)\s*=\s*true",
    re.MULTILINE,
)
_BMW_GIT_ENV_KEYS = (
    "Digital-3D-Car-Repo",
    "SG_BMW_CAR_MODELS_ROOT",
    "SG_CARMODELS_REPO",
    "SG-CarModels-Repo",
)


@dataclass(frozen=True)
class CountryVariantRow:
    source_kind: str
    source_root: str
    brand: str
    model_id: str
    relative_path: str
    test_name: str
    variant_name: str
    variant_base: str
    country_variant_id: str
    configuration_args: tuple[str, ...]
    line_number: int
    config_path: str
    expected_path: str
    actual_path: str
    diff_path: str
    expected_present: bool
    actual_present: bool
    diff_present: bool
    reference_country: str
    reference_country_id: str
    review_flags: tuple[str, ...]

    @property
    def has_runtime_evidence(self) -> bool:
        return self.actual_present or self.diff_present

    @property
    def needs_review(self) -> bool:
        return bool(self.review_flags)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_root": self.source_root,
            "brand": self.brand,
            "model_id": self.model_id,
            "relative_path": self.relative_path,
            "test_name": self.test_name,
            "variant_name": self.variant_name,
            "variant_base": self.variant_base,
            "country_variant_id": self.country_variant_id,
            "configuration_args": list(self.configuration_args),
            "line_number": self.line_number,
            "config_path": self.config_path,
            "expected_path": self.expected_path,
            "actual_path": self.actual_path,
            "diff_path": self.diff_path,
            "expected_present": self.expected_present,
            "actual_present": self.actual_present,
            "diff_present": self.diff_present,
            "has_runtime_evidence": self.has_runtime_evidence,
            "reference_country": self.reference_country,
            "reference_country_id": self.reference_country_id,
            "review_flags": list(self.review_flags),
            "needs_review": self.needs_review,
        }


@dataclass(frozen=True)
class CountryVariantExpectation:
    source_kind: str
    car: str
    feature: str
    expected_variants: tuple[str, ...]
    observed_rows: tuple[str, ...]
    source_path: str
    review_label: str
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "car": self.car,
            "feature": self.feature,
            "expected_variants": list(self.expected_variants),
            "observed_rows": list(self.observed_rows),
            "source_path": self.source_path,
            "review_label": self.review_label,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CountryVariantBoard:
    repo_root: Path
    source_state: str
    generated_at_utc: str
    delivery_entry_total: int
    entries: tuple[CountryVariantRow, ...]
    expectations: tuple[CountryVariantExpectation, ...]
    reference_table: dict[str, str]
    no_config_entries: tuple[str, ...]
    bmw_repo_root: str = ""
    manual_review_banner: str = EVIDENCE_ONLY_BANNER

    @property
    def counts(self) -> dict[str, Any]:
        variant_counts = Counter(entry.variant_name for entry in self.entries)
        country_id_counts = Counter(entry.country_variant_id for entry in self.entries if entry.country_variant_id)
        return {
            "delivery_entry_total": self.delivery_entry_total,
            "row_total": len(self.entries),
            "car_with_rows_count": len({entry.relative_path for entry in self.entries}),
            "no_config_count": len(self.no_config_entries),
            "expected_present_count": sum(1 for entry in self.entries if entry.expected_present),
            "expected_missing_count": sum(1 for entry in self.entries if not entry.expected_present),
            "actual_present_count": sum(1 for entry in self.entries if entry.actual_present),
            "diff_present_count": sum(1 for entry in self.entries if entry.diff_present),
            "runtime_evidence_row_count": sum(1 for entry in self.entries if entry.has_runtime_evidence),
            "no_runtime_row_count": sum(1 for entry in self.entries if not entry.has_runtime_evidence),
            "mapping_review_count": sum(1 for entry in self.entries if MAPPING_REVIEW_LABEL in entry.review_flags),
            "review_row_count": sum(1 for entry in self.entries if entry.review_flags),
            "expectation_count": len(self.expectations),
            "variant_counts": dict(sorted(variant_counts.items())),
            "country_variant_id_counts": dict(sorted(country_id_counts.items(), key=lambda item: _sort_numeric_text(item[0]))),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repo_root": str(self.repo_root),
            "source_state": self.source_state,
            "generated_at_utc": self.generated_at_utc,
            "delivery_entry_total": self.delivery_entry_total,
            "manual_review_banner": self.manual_review_banner,
            "missing_expected_label": MISSING_EXPECTED_LABEL,
            "mapping_review_label": MAPPING_REVIEW_LABEL,
            "no_runtime_label": NO_RUNTIME_LABEL,
            "bmw_repo_root": self.bmw_repo_root,
            "counts": self.counts,
            "reference_table": dict(self.reference_table),
            "no_config_entries": list(self.no_config_entries),
            "entries": [entry.to_dict() for entry in self.entries],
            "expectations": [expectation.to_dict() for expectation in self.expectations],
        }


def _sort_numeric_text(value: str) -> tuple[int, str]:
    text = str(value)
    return (int(text), text) if text.isdigit() else (10**9, text)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _split_lua_args(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.replace("\n", " ").split(","))


def _variant_name(test_name: str) -> str:
    return test_name[len("countryCoding_") :] if test_name.startswith("countryCoding_") else test_name


def _variant_base(variant_name: str) -> str:
    for country in (
        "Australia",
        "Canada",
        "China",
        "Egypt",
        "Honkong",
        "Hongkong",
        "Japan",
        "Korea",
        "Mexico",
        "Taiwan",
        "US",
        "ECE",
        "Russia",
        "Turkey",
        "Germany",
        "England",
    ):
        if variant_name == country or variant_name.startswith(country + "_"):
            return country
    return variant_name.split("_", 1)[0]


def _normal_country_name(value: str) -> str:
    text = "".join(ch for ch in str(value).strip() if ch.isalnum()).casefold()
    aliases = {
        "hongkong": "Honkong",
        "honkong": "Honkong",
        "usa": "US",
        "us": "US",
        "ece": "ECE",
    }
    return aliases.get(text, str(value).strip())


def _discover_bmw_repo_root(workspace_root: Path | None, explicit_root: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit_root is not None:
        candidates.append(explicit_root)
    for key in _BMW_GIT_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            candidates.append(Path(value))
    if workspace_root is not None:
        workspace = Path(workspace_root)
        candidates.extend(
            (
                workspace / "digital-3d-car-models",
                workspace / "external" / "digital-3d-car-models",
                workspace.parent / "digital-3d-car-models",
            )
        )
    candidates.append(Path(r"C:\3D Car git\digital-3d-car-models"))
    candidates.append(Path(r"C:\repos\digital-3d-car-models"))
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "cars").is_dir() or (root / "ci").is_dir():
            return root
    return None


def _reference_table_from_readme(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    text = _read_text(path)
    section_match = re.search(r"^##\s+Country Variant IDs\s*$", text, re.MULTILINE)
    if section_match is None:
        return {}
    section = text[section_match.end() :]
    next_section = re.search(r"^\s*(?:---|##\s+)", section, re.MULTILINE)
    if next_section is not None:
        section = section[: next_section.start()]
    table: dict[str, str] = {}
    for match in _COUNTRY_TABLE_ROW_RE.finditer(section):
        country = _normal_country_name(match.group("country"))
        if country:
            table[country] = match.group("id").strip()
    return table


def _reference_table_from_logic(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    table: dict[str, str] = {}
    for match in _LOGIC_COUNTRY_RE.finditer(_read_text(path)):
        country = _normal_country_name(match.group("country"))
        if country:
            table[country] = match.group("id").strip()
    return table


def _country_reference_table(repo_root: Path, entry: DeliveryReadinessEntry | None, model_dir: Path | None = None) -> dict[str, str]:
    brand = entry.brand if entry is not None else ""
    source_root = entry.source_root if entry is not None else ""
    tables: list[dict[str, str]] = []
    if brand:
        tables.append(_reference_table_from_readme(repo_root / source_root / brand / "README.md"))
    if model_dir is not None:
        tables.append(_reference_table_from_logic(model_dir / "main" / "scripts" / "Logic_CountryVariants.lua"))
    for table in tables:
        if table:
            return table
    return {}


def _entry_config_path(repo_root: Path, entry: DeliveryReadinessEntry) -> Path:
    return repo_root / Path(entry.relative_path) / CONFIG_RELATIVE_PATH


def _build_country_rows_for_config(
    *,
    source_kind: str,
    source_root: str,
    brand: str,
    model_id: str,
    relative_path: str,
    config_path: Path,
    reference_table: dict[str, str],
) -> tuple[CountryVariantRow, ...]:
    if not config_path.is_file():
        return ()
    text = strip_lua_comments(_read_text(config_path))
    rows: list[CountryVariantRow] = []
    tests_root = config_path.parent
    for match in _ADD_COUNTRY_TEST_RE.finditer(text):
        test_name = match.group("name")
        variant = _variant_name(test_name)
        base = _normal_country_name(_variant_base(variant))
        config_match = _CONFIGURATION_RE.search(match.group("body"))
        args = _split_lua_args(config_match.group("args")) if config_match is not None else ()
        country_id = args[3] if len(args) >= 4 else ""
        expected_path = tests_root / "expected" / f"{test_name}.png"
        actual_path = tests_root / "actual" / f"{test_name}.png"
        diff_path = tests_root / "diff" / f"{test_name}.png"
        reference_id = reference_table.get(base, "")
        flags: list[str] = []
        if not expected_path.is_file():
            flags.append(MISSING_EXPECTED_LABEL)
        if reference_id and country_id and country_id != reference_id:
            flags.append(MAPPING_REVIEW_LABEL)
        rows.append(
            CountryVariantRow(
                source_kind=source_kind,
                source_root=source_root,
                brand=brand,
                model_id=model_id,
                relative_path=relative_path,
                test_name=test_name,
                variant_name=variant,
                variant_base=base,
                country_variant_id=country_id,
                configuration_args=args,
                line_number=text.count("\n", 0, match.start()) + 1,
                config_path=str(config_path),
                expected_path=str(expected_path),
                actual_path=str(actual_path),
                diff_path=str(diff_path),
                expected_present=expected_path.is_file(),
                actual_present=actual_path.is_file(),
                diff_present=diff_path.is_file(),
                reference_country=base if reference_id else "",
                reference_country_id=reference_id,
                review_flags=tuple(dict.fromkeys(flags)),
            )
        )
    return tuple(rows)


def _model_dir_for_bmw_git(bmw_root: Path, car: str) -> Path | None:
    candidates = [
        bmw_root / "cars" / "BMW" / f"{car}_EVO",
        bmw_root / "cars" / "BMW" / car,
        bmw_root / "cars" / "MINI" / car,
        bmw_root / "cars" / "RR" / car,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _expectation_rows(
    repo_root: Path,
    bmw_repo_root: Path | None,
    existing_rows: tuple[CountryVariantRow, ...],
) -> tuple[CountryVariantExpectation, ...]:
    expectation = country_variant_lightfx_expectations("G50")
    expected_variants = tuple(str(item) for item in expectation.get("expected_selective_yellow_country_variants", ()))
    if not expected_variants:
        return ()
    observed_rows = tuple(
        row.test_name
        for row in existing_rows
        if row.model_id.upper() == "G50" or row.model_id.upper() == "G50_EVO"
    )
    notes = list(str(item) for item in expectation.get("evidence", ()))
    source_path = "sg_preflight.bmw_process.country_variant_lightfx_expectations"
    if bmw_repo_root is not None:
        model_dir = _model_dir_for_bmw_git(bmw_repo_root, "G50")
        if model_dir is not None:
            config_path = model_dir / CONFIG_RELATIVE_PATH
            git_rows = _build_country_rows_for_config(
                source_kind="bmw_git",
                source_root=str(bmw_repo_root),
                brand="BMW",
                model_id="G50",
                relative_path=str(model_dir.relative_to(bmw_repo_root)).replace("\\", "/"),
                config_path=config_path,
                reference_table=_country_reference_table(repo_root, None, model_dir),
            )
            if git_rows:
                observed_rows = tuple(row.test_name for row in git_rows)
                source_path = str(config_path)
    return (
        CountryVariantExpectation(
            source_kind="process_expectation",
            car=str(expectation.get("car", "G50")),
            feature=str(expectation.get("feature", "Country-variant LightFX")),
            expected_variants=expected_variants,
            observed_rows=observed_rows,
            source_path=source_path,
            review_label="expected variants should be checked in the country-variant matrix - review",
            notes=tuple(notes),
        ),
    )


def build_country_variant_coverage_board(
    repo_root: Path | None = None,
    *,
    workspace_root: Path | None = None,
    bmw_repo_root: Path | None = None,
) -> CountryVariantBoard:
    delivery_board = build_delivery_readiness_board(
        repo_root,
        workspace_root=workspace_root,
        bmw_repo_root=bmw_repo_root,
    )
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if delivery_board.source_state != "ready":
        return CountryVariantBoard(
            repo_root=delivery_board.repo_root,
            source_state=delivery_board.source_state,
            generated_at_utc=generated_at,
            delivery_entry_total=0,
            entries=(),
            expectations=(),
            reference_table={},
            no_config_entries=(),
        )

    rows: list[CountryVariantRow] = []
    no_config_entries: list[str] = []
    reference_table: dict[str, str] = {}
    for entry in delivery_board.entries:
        config_path = _entry_config_path(delivery_board.repo_root, entry)
        if not config_path.is_file():
            no_config_entries.append(entry.relative_path)
            continue
        model_dir = delivery_board.repo_root / Path(entry.relative_path)
        table = _country_reference_table(delivery_board.repo_root, entry, model_dir)
        reference_table.update({country: value for country, value in table.items() if country not in reference_table})
        rows.extend(
            _build_country_rows_for_config(
                source_kind="svn_trunk",
                source_root=entry.source_root,
                brand=entry.brand,
                model_id=entry.model_id,
                relative_path=entry.relative_path,
                config_path=config_path,
                reference_table=table,
            )
        )
    bmw_root = _discover_bmw_repo_root(workspace_root, bmw_repo_root)
    expectations = _expectation_rows(delivery_board.repo_root, bmw_root, tuple(rows))
    return CountryVariantBoard(
        repo_root=delivery_board.repo_root,
        source_state=delivery_board.source_state,
        generated_at_utc=generated_at,
        delivery_entry_total=len(delivery_board.entries),
        entries=tuple(sorted(rows, key=lambda row: (row.source_root, row.brand, row.model_id, row.test_name))),
        expectations=expectations,
        reference_table=dict(sorted(reference_table.items())),
        no_config_entries=tuple(sorted(no_config_entries)),
        bmw_repo_root=str(bmw_root) if bmw_root is not None else "",
    )


def country_variant_coverage_markdown(board: CountryVariantBoard) -> str:
    payload = board.to_dict()
    counts = payload["counts"]
    lines = [
        "# Country-Variant Coverage",
        "",
        EVIDENCE_ONLY_BANNER,
        "",
        f"- source: `{payload['repo_root']}`",
        f"- generated: `{payload['generated_at_utc']}`",
        f"- country-coding rows: {counts['row_total']}",
        f"- cars with rows: {counts['car_with_rows_count']}",
        f"- expected baselines present: {counts['expected_present_count']}/{counts['row_total']}",
        f"- actual screenshots present: {counts['actual_present_count']}",
        f"- diff screenshots present: {counts['diff_present_count']}",
        f"- review rows: {counts['review_row_count']}",
        "",
        "| Source | Brand | Model | Test | Variant | CountryVariant_ID | Expected | Actual | Diff | Review flags |",
        "| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for entry in board.entries:
        lines.append(
            "| "
            + " | ".join(
                (
                    entry.source_root,
                    entry.brand,
                    entry.model_id,
                    entry.test_name,
                    entry.variant_name,
                    entry.country_variant_id,
                    "yes" if entry.expected_present else "no",
                    "yes" if entry.actual_present else "no",
                    "yes" if entry.diff_present else "no",
                    "; ".join(entry.review_flags).replace("|", "\\|"),
                )
            )
            + " |"
        )
    if board.expectations:
        lines.extend(("", "## Process Expectations", ""))
        for expectation in board.expectations:
            lines.append(
                f"- {expectation.car}: {expectation.feature}; expected "
                f"{', '.join(expectation.expected_variants)}; observed rows "
                f"{', '.join(expectation.observed_rows) or 'none'}; {expectation.review_label}."
            )
    return "\n".join(lines).rstrip() + "\n"


def write_country_variant_coverage_board(board: CountryVariantBoard, output_root: Path) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "country-variant-coverage.json"
    markdown_path = output_root / "country-variant-coverage.md"
    json_path.write_text(json.dumps(board.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(country_variant_coverage_markdown(board), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
