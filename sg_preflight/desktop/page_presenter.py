from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from sg_preflight.surface_registry import RENDERER_KINDS, SurfaceDescriptor, get_surface_descriptor


_ITEM_KEYS = (
    "itemId",
    "sectionId",
    "label",
    "value",
    "detail",
    "status",
    "expected",
    "actual",
    "diff",
    "source",
    "revision",
)
_FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "args",
        "argv",
        "command",
        "commands",
        "environment",
        "executable",
        "executables",
        "href",
        "launch_command",
        "session_path",
        "svg",
        "uri",
        "url",
    }
)
_EVIDENCE_SUMMARY_MAX_LENGTH = 2_000
_UNSAFE_EVIDENCE_SUMMARY = re.compile(
    r"(?i)(?:[a-z][a-z0-9+.-]*://|[a-z]:[\\/]|\\\\[^\\/\s]+[\\/]|(?:^|\s)/(?:[^/\s]+/)+)"
)
_REQUIRED_FIELDS: dict[str, tuple[tuple[str, type], ...]] = {
    "full-qa-pass": (("progress", dict), ("steps", list)),
    "batch-full-qa-pass": (("progress", dict), ("results", list)),
    "delivery-checklist": (("checks", list),),
    "disabled-tests": (("counts", dict), ("baseline", dict), ("board_rows", list)),
    "api-version-coverage": (
        ("counts", dict),
        ("shared_api_references", list),
        ("interface_family_entries", list),
        ("impact_scans", list),
    ),
    "country-variant-coverage": (("counts", dict), ("entries", list), ("expectations", list)),
    "export-size-trend": (("counts", dict), ("trend_changes", list), ("workbooks", list)),
    "onboarding-guide": (("steps", list),),
    "setup-doctor": (("version_validation", dict), ("board_rows", list)),
    "qa-workflows": (("workflows", list), ("board_rows", list)),
    "bmw-process": (("contracts", list),),
    "screenshot-test-state": (
        ("display_type_groups", list),
        ("rack_readiness_entries", list),
        ("operator_checklist", list),
    ),
    "risk-score": (("signals", list),),
    "cross-car-comparison": (("comparison_rows", list),),
    "daily-digest": (("sections", dict),),
    "team-digest-board": (("sections", dict),),
    "operator-handoff": (("handoff_items", list),),
    "manual-review": (("steps", list),),
}


class PagePresentationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _SectionSpec:
    section_id: str
    title: str


def _reject() -> None:
    raise PagePresentationError("The page payload cannot be presented safely.")


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")


def _reject_forbidden_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _normalized_key(key) in _FORBIDDEN_INPUT_KEYS:
                _reject()
            _reject_forbidden_fields(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        for item in value:
            _reject_forbidden_fields(item)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _reject()
    return value


def _records(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        _reject()
    records: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            _reject()
        records.append(item)
    return records


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return ", ".join(part for part in (_text(item) for item in value) if part)
    return ""


def _evidence_summary_text(value: object) -> str:
    text = _text(value).strip()
    if (
        len(text) > _EVIDENCE_SUMMARY_MAX_LENGTH
        or any(ord(character) < 32 and character not in {"\n", "\r", "\t"} for character in text)
        or _UNSAFE_EVIDENCE_SUMMARY.search(text)
    ):
        _reject()
    return text


def _first(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(record.get(key))
        if value:
            return value
    return ""


def _joined(record: Mapping[str, Any], *keys: str) -> str:
    return " · ".join(value for value in (_text(record.get(key)) for key in keys) if value)


def _item(
    section_id: str,
    index: int,
    *,
    label: object = "",
    value: object = "",
    detail: object = "",
    status: object = "",
    expected: object = "",
    actual: object = "",
    diff: object = "",
    source: object = "",
    revision: object = "",
) -> dict[str, str]:
    output = {
        "itemId": f"{section_id}-{index + 1}",
        "sectionId": section_id,
        "label": _text(label),
        "value": _text(value),
        "detail": _text(detail),
        "status": _text(status),
        "expected": _text(expected),
        "actual": _text(actual),
        "diff": _text(diff),
        "source": _text(source),
        "revision": _text(revision),
    }
    if tuple(output) != _ITEM_KEYS:
        _reject()
    return output


def _record_items(
    section_id: str,
    records: list[Mapping[str, Any]],
    *,
    label_keys: tuple[str, ...],
    value_keys: tuple[str, ...],
    detail_keys: tuple[str, ...] = (),
    status_keys: tuple[str, ...] = ("status",),
    source_keys: tuple[str, ...] = ("source",),
    revision_keys: tuple[str, ...] = ("revision",),
) -> list[dict[str, str]]:
    return [
        _item(
            section_id,
            index,
            label=_first(record, *label_keys),
            value=_first(record, *value_keys),
            detail=_joined(record, *detail_keys),
            status=_first(record, *status_keys),
            source=_first(record, *source_keys),
            revision=_first(record, *revision_keys),
        )
        for index, record in enumerate(records)
    ]


def _progress_item(section_id: str, progress: Mapping[str, Any]) -> dict[str, str]:
    completed = _first(progress, "completed_steps", "completed_profiles", "completed", "current")
    total = _first(progress, "total_steps", "total_profiles", "total")
    percent = _first(progress, "percent")
    value = f"{completed}/{total}" if completed or total else percent
    detail = f"{percent}%" if percent and percent not in value else ""
    return _item(section_id, 0, label="Progress", value=value or "Not started", detail=detail)


def _surface_items(surface_id: str, payload: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[_SectionSpec]]:
    if surface_id == "full-qa-pass":
        items = [_progress_item("progress", _mapping(payload["progress"]))]
        items.extend(
            _record_items(
                "steps",
                _records(payload["steps"]),
                label_keys=("label", "title", "id", "key"),
                value_keys=("summary", "detail", "label", "title"),
                detail_keys=("evidence", "note"),
            )
        )
        specs = [_SectionSpec("progress", "Progress"), _SectionSpec("steps", "QA steps")]
        evidence_summary = _evidence_summary_text(payload.get("evidence_summary", ""))
        if evidence_summary:
            items.append(
                _item(
                    "evidence-summary",
                    0,
                    label="Copy-ready Jira evidence",
                    value=evidence_summary,
                    status="local evidence",
                )
            )
            specs.append(_SectionSpec("evidence-summary", "Copy-ready evidence"))
        return items, specs
    if surface_id == "batch-full-qa-pass":
        items = [_progress_item("progress", _mapping(payload["progress"]))]
        items.extend(
            _record_items(
                "results",
                _records(payload["results"]),
                label_keys=("profile_id", "label", "id"),
                value_keys=("summary", "profile_id", "detail"),
            )
        )
        return items, [_SectionSpec("progress", "Progress"), _SectionSpec("results", "Profile results")]
    if surface_id == "delivery-checklist":
        items = _record_items(
            "checks",
            _records(payload["checks"]),
            label_keys=("label", "key", "name"),
            value_keys=("raw_value", "value", "detail", "label"),
            detail_keys=("note", "sheet", "cell"),
            revision_keys=("revision", "generated_at_utc"),
        )
        return items, [_SectionSpec("checks", "Delivery evidence")]
    if surface_id == "disabled-tests":
        items = _record_items(
            "rows",
            _records(payload["board_rows"]),
            label_keys=("label", "key"),
            value_keys=("detail", "value", "label"),
        )
        counts = _mapping(payload["counts"])
        items.append(_item("counts", 0, label="Disabled tests", value=_joined(counts, *sorted(counts))))
        return items, [_SectionSpec("rows", "Disabled tests"), _SectionSpec("counts", "Counts")]
    if surface_id == "api-version-coverage":
        references = _record_items(
            "references",
            _records(payload["shared_api_references"]),
            label_keys=("brand", "label", "name"),
            value_keys=("current_version", "version", "brand"),
            detail_keys=("current_date", "status"),
        )
        families = _record_items(
            "families",
            _records(payload["interface_family_entries"]),
            label_keys=("model_id", "brand", "label"),
            value_keys=("hmi_interface_version", "hmi_family_label", "model_id"),
            detail_keys=("hmi_family_label", "match_status", "catalog_name"),
        )
        impacts = _record_items(
            "impacts",
            _records(payload["impact_scans"]),
            label_keys=("label", "matched_car_count", "id"),
            value_keys=("matched_file_count", "matched_car_count", "status"),
            detail_keys=("status", "review_label"),
        )
        return references + families + impacts, [
            _SectionSpec("references", "Shared API references"),
            _SectionSpec("families", "Interface families"),
            _SectionSpec("impacts", "Impact scans"),
        ]
    if surface_id == "country-variant-coverage":
        entries = []
        for index, record in enumerate(_records(payload["entries"])):
            entries.append(
                _item(
                    "entries",
                    index,
                    label=_first(record, "test_name", "label", "country_variant_id"),
                    value=_first(record, "country_variant_id", "variant_name", "test_name"),
                    detail=_joined(record, "brand", "model_id", "variant_name", "relative_path"),
                    status=_first(record, "status", "review_label"),
                    expected=_first(record, "expected_path", "expected"),
                    actual=_first(record, "actual_path", "actual"),
                    diff=_first(record, "diff_path", "diff"),
                    revision=_first(record, "revision"),
                )
            )
        expectations = _record_items(
            "expectations",
            _records(payload["expectations"]),
            label_keys=("car", "feature", "label"),
            value_keys=("feature", "review_label", "car"),
            detail_keys=("expected_variants", "observed_rows", "review_label"),
            status_keys=("status", "review_label"),
        )
        return entries + expectations, [
            _SectionSpec("entries", "Country rows"),
            _SectionSpec("expectations", "Expectations"),
        ]
    if surface_id == "export-size-trend":
        changes = _record_items(
            "changes",
            _records(payload["trend_changes"]),
            label_keys=("profile_id", "label", "id"),
            value_keys=("delta_total", "delta_percent", "profile_id"),
            detail_keys=("delta_percent", "review_flags", "previous_workbook", "current_workbook"),
        )
        workbooks = _record_items(
            "workbooks",
            _records(payload["workbooks"]),
            label_keys=("relative_path", "label", "profile_id"),
            value_keys=("status", "relative_path", "profile_id"),
            detail_keys=("review_flags", "layout", "date"),
        )
        return changes + workbooks, [_SectionSpec("changes", "Trend changes"), _SectionSpec("workbooks", "Workbooks")]
    if surface_id == "onboarding-guide":
        items = _record_items(
            "steps",
            _records(payload["steps"]),
            label_keys=("label", "title", "id", "key"),
            value_keys=("summary", "detail", "label", "title"),
            detail_keys=("guidance", "note"),
        )
        return items, [_SectionSpec("steps", "Onboarding steps")]
    if surface_id == "setup-doctor":
        items = _record_items(
            "rows",
            _records(payload["board_rows"]),
            label_keys=("label", "key"),
            value_keys=("detail", "value", "label"),
        )
        validation = _mapping(payload["version_validation"])
        items.append(_item("versions", 0, label="Version validation", value=_joined(validation, *sorted(validation))))
        return items, [_SectionSpec("rows", "Setup checks"), _SectionSpec("versions", "Versions")]
    if surface_id == "qa-workflows":
        items = _record_items(
            "workflows",
            _records(payload["workflows"]),
            label_keys=("name", "id", "label"),
            value_keys=("last_status", "check_count", "name"),
            detail_keys=("check_count", "dod_count", "profiles"),
        )
        return items, [_SectionSpec("workflows", "QA workflows")]
    if surface_id == "bmw-process":
        items = _record_items(
            "contracts",
            _records(payload["contracts"]),
            label_keys=("label", "key", "name"),
            value_keys=("label", "source", "key"),
            detail_keys=("steps", "evidence"),
        )
        return items, [_SectionSpec("contracts", "Process contracts")]
    if surface_id == "screenshot-test-state":
        groups = _record_items(
            "display-types",
            _records(payload["display_type_groups"]),
            label_keys=("label", "display_type", "name"),
            value_keys=("count", "status", "label"),
            detail_keys=("detail", "expected", "actual", "diff"),
        )
        rack = _record_items(
            "rack",
            _records(payload["rack_readiness_entries"]),
            label_keys=("label", "rack", "name"),
            value_keys=("status", "count", "label"),
            detail_keys=("detail",),
        )
        checklist = _record_items(
            "checklist",
            _records(payload["operator_checklist"]),
            label_keys=("label", "key", "name"),
            value_keys=("status", "detail", "label"),
            detail_keys=("detail",),
        )
        return groups + rack + checklist, [
            _SectionSpec("display-types", "Display types"),
            _SectionSpec("rack", "Rack readiness"),
            _SectionSpec("checklist", "Operator checklist"),
        ]
    if surface_id == "risk-score":
        items = [
            _item(
                "score",
                0,
                label="Risk score",
                value=_first(payload, "risk_score", "risk_level"),
                detail=_first(payload, "risk_level"),
                status=_first(payload, "risk_level", "status"),
            )
        ]
        items.extend(
            _record_items(
                "signals",
                _records(payload["signals"]),
                label_keys=("id", "label", "name"),
                value_keys=("detail", "value", "id"),
            )
        )
        return items, [_SectionSpec("score", "Risk score"), _SectionSpec("signals", "Signals")]
    if surface_id == "cross-car-comparison":
        items = []
        for index, record in enumerate(_records(payload["comparison_rows"])):
            items.append(
                _item(
                    "comparison",
                    index,
                    label=_first(record, "label", "axis", "id"),
                    value=_first(record, "delta_label", "label"),
                    detail=_joined(record, "left_profile", "right_profile"),
                    status=_first(record, "status"),
                    expected=_first(record, "left_value", "expected"),
                    actual=_first(record, "right_value", "actual"),
                    diff=_first(record, "delta_label", "diff"),
                )
            )
        return items, [_SectionSpec("comparison", "Comparison")]
    if surface_id in {"daily-digest", "team-digest-board"}:
        sections = _mapping(payload["sections"])
        items: list[dict[str, str]] = []
        specs: list[_SectionSpec] = []
        for section_index, (raw_key, raw_section) in enumerate(sections.items()):
            section_id = _normalized_key(raw_key) or f"section-{section_index + 1}"
            section = _mapping(raw_section)
            title = _first(section, "heading", "title", "label") or str(raw_key).replace("_", " ").title()
            specs.append(_SectionSpec(section_id, title))
            items.append(
                _item(
                    section_id,
                    0,
                    label=title,
                    value=title,
                    status=_first(section, "status"),
                )
            )
            section_records = section.get("items", [])
            if isinstance(section_records, list) and section_records:
                records = _records(section_records)
                start = len(items)
                items.extend(
                    _record_items(
                        section_id,
                        records,
                        label_keys=("label", "profile_id", "title", "id"),
                        value_keys=("detail", "summary", "risk_score", "status", "label"),
                        detail_keys=("detail", "note"),
                    )
                )
                for offset, item in enumerate(items[start:], start=2):
                    item["itemId"] = f"{section_id}-{offset}"
            elif _first(section, "empty_message", "count"):
                items.append(
                    _item(
                        section_id,
                        1,
                        label="Evidence count",
                        value=_first(section, "count") or "No items",
                        detail=_first(section, "empty_message"),
                        status=_first(section, "status"),
                    )
                )
        if surface_id == "team-digest-board":
            share = payload.get("share_decision", {})
            if isinstance(share, Mapping):
                items.append(
                    _item(
                        "sharing",
                        0,
                        label="Sharing model",
                        value=_first(share, "selected_model", "status", "rationale"),
                        detail=_first(share, "rationale"),
                        status=_first(share, "status"),
                    )
                )
                specs.append(_SectionSpec("sharing", "Sharing"))
        return items, specs
    if surface_id == "operator-handoff":
        items = _record_items(
            "handoff",
            _records(payload["handoff_items"]),
            label_keys=("label", "key", "id"),
            value_keys=("detail", "value", "label"),
        )
        latest = payload.get("latest_handoff")
        if isinstance(latest, Mapping) and latest:
            items.insert(
                0,
                _item(
                    "latest",
                    0,
                    label="Latest handoff",
                    value=_first(latest, "summary", "stopping_point", "note", "status"),
                    detail=_first(latest, "next_step"),
                    status=_first(latest, "status"),
                    revision=_first(latest, "revision", "recorded_at_utc"),
                ),
            )
        return items, [_SectionSpec("latest", "Latest handoff"), _SectionSpec("handoff", "Handoff items")]
    if surface_id == "manual-review":
        steps = _records(payload["steps"])
        if len(steps) != 7:
            _reject()
        items = _record_items(
            "steps",
            steps,
            label_keys=("label", "title", "id", "slug"),
            value_keys=("summary", "detail", "verdict", "label", "title"),
            detail_keys=("evidence_prompt", "suggestion_reason", "note"),
            status_keys=("status", "verdict", "suggestion_status"),
        )
        for item, step in zip(items, steps, strict=True):
            step_id = _first(step, "slug", "id", "key")
            if step_id:
                item["itemId"] = step_id
        return items, [_SectionSpec("steps", "Manual review steps")]
    _reject()


def _sections(
    items: list[dict[str, str]],
    specs: list[_SectionSpec],
    status: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in specs:
        if spec.section_id in seen:
            continue
        seen.add(spec.section_id)
        section_items = [dict(item) for item in items if item["sectionId"] == spec.section_id]
        if section_items:
            output.append(
                {
                    "sectionId": spec.section_id,
                    "title": spec.title,
                    "status": status,
                    "items": section_items,
                }
            )
    return output


def _truth(payload: Mapping[str, Any], page: Mapping[str, Any], key: str, fallback: bool) -> bool:
    if key in payload:
        return bool(payload[key])
    if key in page:
        return bool(page[key])
    return fallback


def _provenance(payload: Mapping[str, Any], page: Mapping[str, Any]) -> dict[str, str]:
    raw = payload.get("provenance", page.get("provenance", {}))
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, Mapping):
        _reject()
    return {
        "source": _first(raw, "source", "kind", "label"),
        "revision": _first(raw, "revision", "version", "generated_at_utc"),
    }


def _present_about(descriptor: SurfaceDescriptor, page: Mapping[str, Any]) -> dict[str, Any]:
    content = _mapping(page.get("content"))
    _reject_forbidden_fields(content)
    description = _first(content, "description")
    if not description:
        _reject()
    items = [_item("scope", 0, label="Scope", value=description)]
    version = _first(content, "version_placeholder", "version")
    if version:
        items.append(_item("scope", 1, label="Version", value=version))
    disclosure = content.get("data_handling_disclosure", ())
    if disclosure:
        if isinstance(disclosure, str):
            disclosure = (disclosure,)
        elif not isinstance(disclosure, Sequence) or isinstance(disclosure, (bytes, bytearray, memoryview)):
            _reject()
        for index, value in enumerate(disclosure):
            text = _text(value)
            if text:
                items.append(_item("handling", index, label="Data handling", value=text))
    provenance = _provenance(content, page)
    if provenance["source"] or provenance["revision"]:
        items.append(
            _item(
                "provenance",
                0,
                label="Provenance",
                value=provenance["source"],
                revision=provenance["revision"],
            )
        )
    status = _first(content, "status")
    return {
        "surfaceId": descriptor.surface_id,
        "rendererKind": descriptor.renderer_kind,
        "title": descriptor.title,
        "subtitle": descriptor.subtitle,
        "status": status,
        "dataAvailable": True,
        "primaryText": description,
        "visibleItems": items,
        "visibleItemCount": len(items),
        "sections": _sections(
            items,
            [
                _SectionSpec("scope", "Scope"),
                _SectionSpec("handling", "Data handling"),
                _SectionSpec("provenance", "Provenance"),
            ],
            status,
        ),
        "actions": [],
        "artifacts": [],
        "provenance": provenance,
        "ownershipNote": _first(content, "ownership_note"),
        "readOnly": _truth(content, page, "read_only", True),
        "isApproval": _truth(content, page, "is_approval", False),
        "manualReviewRequired": _truth(content, page, "manual_review_required", False),
        "recordsOperatorVerdict": _truth(content, page, "records_operator_verdict", False),
    }


def present_page_payload(
    descriptor: SurfaceDescriptor,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(descriptor, SurfaceDescriptor) or not isinstance(payload, Mapping):
        _reject()
    try:
        registered = get_surface_descriptor(descriptor.surface_id)
    except KeyError:
        _reject()
    if descriptor != registered or descriptor.renderer_kind not in RENDERER_KINDS or descriptor.surface_id == "home":
        _reject()
    if str(payload.get("id", "")) != descriptor.surface_id:
        _reject()
    if descriptor.surface_id == "about":
        return _present_about(descriptor, payload)
    if not descriptor.operational:
        _reject()
    nested = _mapping(payload.get("payload"))
    for key, expected_type in _REQUIRED_FIELDS[descriptor.surface_id]:
        if key not in nested or not isinstance(nested[key], expected_type):
            _reject()
        _reject_forbidden_fields(nested[key])
    if descriptor.surface_id == "manual-review" and len(_records(nested["steps"])) != 7:
        _reject()
    status = _first(nested, "status") if "status" in nested else _first(payload, "status")
    data_available = _truth(nested, payload, "data_available", False)
    items, specs = _surface_items(descriptor.surface_id, nested)
    summary = _first(nested, "summary") or _first(payload, "summary", "empty_state_note")
    if not items:
        items = [
            _item(
                "state",
                0,
                label="Evidence state",
                value=summary or status or "No local evidence available",
                status=status,
            )
        ]
        specs.append(_SectionSpec("state", "Evidence state"))
    primary = summary
    if not primary:
        first_item = items[0]
        primary = first_item["value"] or first_item["detail"] or first_item["label"]
    provenance = _provenance(nested, payload)
    output = {
        "surfaceId": descriptor.surface_id,
        "rendererKind": descriptor.renderer_kind,
        "title": descriptor.title,
        "subtitle": descriptor.subtitle,
        "status": status,
        "dataAvailable": data_available,
        "primaryText": primary,
        "visibleItems": items,
        "visibleItemCount": len(items),
        "sections": _sections(items, specs, status),
        "actions": [],
        "artifacts": [],
        "provenance": provenance,
        "ownershipNote": _first(nested, "ownership_note") or _first(payload, "ownership_note"),
        "readOnly": _truth(nested, payload, "read_only", True),
        "isApproval": _truth(nested, payload, "is_approval", False),
        "manualReviewRequired": _truth(
            nested,
            payload,
            "manual_review_required",
            descriptor.surface_id in {"full-qa-pass", "batch-full-qa-pass", "manual-review"},
        ),
        "recordsOperatorVerdict": _truth(
            nested,
            payload,
            "records_operator_verdict",
            descriptor.surface_id == "manual-review",
        ),
    }
    return output


def build_presented_sections(
    descriptor: SurfaceDescriptor,
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return list(present_page_payload(descriptor, payload)["sections"])


def build_presented_actions(
    descriptor: SurfaceDescriptor,
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    present_page_payload(descriptor, payload)
    return []


def build_presented_artifacts(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        _reject()
    return []


def build_presented_provenance(payload: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        _reject()
    return _provenance(payload, {})
