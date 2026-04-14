from __future__ import annotations

import json
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from sg_preflight.adapters.common import find_matches, load_json


SPREADSHEET_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
WORKBOOK_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
LEGACY_COLOR_KEYS = ("BaseColor", "HalftoneColor", "ShadowTint", "HighlightTint")


def _extract_json_blob(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ValueError("Helper script did not print JSON")
    starts = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
    if not starts:
        raise ValueError("Helper output did not contain JSON")
    candidate = text[min(starts):]
    return json.loads(candidate)


def _load_via_helper(helper_path: Path, source_path: Path) -> Any:
    result = subprocess.run(
        [sys.executable, str(helper_path), str(source_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + "\n" + result.stderr)
    return _extract_json_blob(result.stdout)


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _normalize_style_id(value: Any) -> int | float | str | None:
    if value is None:
        return None
    numeric = _to_float(value)
    if numeric is None:
        text = str(value).strip()
        return text or None
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _normalize_color_triplet(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    components = []
    for item in value:
        numeric = _to_float(item)
        if numeric is None:
            return None
        components.append(numeric)

    if max(abs(component) for component in components) > 1.0:
        components = [component / 255.0 for component in components]

    return [round(component, 6) for component in components]


def _infer_finish_fields(name: str, style_id: int | float | str | None) -> tuple[str, float, float, float]:
    del style_id
    lowered = name.lower()
    if any(token in lowered for token in ("matte", "matt", "frozen")):
        return ("matte", 0.75, 0.2, 0.15)
    if any(token in lowered for token in ("metallic", "effect", "brillianteffekt", "chrome")):
        return ("metallic", 0.35, 0.8, 0.6)
    return ("solid", 0.45, 0.0, 0.5)


def _is_legacy_entry(entry: dict[str, Any]) -> bool:
    return any(key in entry for key in ("Code", "StyleID", *LEGACY_COLOR_KEYS))


def _normalize_carpaint_entry(
    entry: dict[str, Any],
    *,
    fallback_id: str | None = None,
    source_format: str | None = None,
    sheet: str | None = None,
) -> dict[str, Any]:
    result = dict(entry)

    paint_id = (
        result.get("id")
        or result.get("Id")
        or result.get("code")
        or result.get("Code")
        or fallback_id
        or "<unknown-paint>"
    )
    name = (
        result.get("name")
        or result.get("Name")
        or result.get("material_name")
        or result.get("Material")
        or fallback_id
        or str(paint_id)
    )

    normalized: dict[str, Any] = {
        "id": str(paint_id).strip(),
        "name": str(name).strip(),
    }

    if source_format:
        normalized["source_format"] = source_format
    if sheet:
        normalized["sheet"] = sheet

    brand = result.get("brand") or result.get("Brand")
    if brand not in (None, ""):
        normalized["brand"] = str(brand).strip()

    style_id = _normalize_style_id(
        result.get("style_id") or result.get("StyleID") or result.get("style")
    )
    if style_id is not None:
        normalized["style_id"] = style_id

    base_color = _normalize_color_triplet(
        result.get("base_color") or result.get("BaseColor")
    )
    if base_color is not None:
        normalized["base_color"] = base_color

    for source_key, target_key in (
        ("HalftoneColor", "halftone_color"),
        ("ShadowTint", "shadow_tint"),
        ("HighlightTint", "highlight_tint"),
    ):
        color = _normalize_color_triplet(result.get(source_key))
        if color is not None:
            normalized[target_key] = color

    inferred_finish, inferred_roughness, inferred_metallic, inferred_clearcoat = (
        _infer_finish_fields(normalized["name"], style_id)
    )

    finish = result.get("finish")
    normalized["finish"] = str(finish).strip() if finish not in (None, "") else inferred_finish

    roughness = _to_float(result.get("roughness"))
    normalized["roughness"] = round(
        roughness if roughness is not None else inferred_roughness,
        6,
    )

    metallic = _to_float(result.get("metallic"))
    normalized["metallic"] = round(
        metallic if metallic is not None else inferred_metallic,
        6,
    )

    clearcoat = _to_float(result.get("clearcoat"))
    normalized["clearcoat"] = round(
        clearcoat if clearcoat is not None else inferred_clearcoat,
        6,
    )

    return normalized


def _normalize_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"carpaints": entries}


def normalize_carpaints_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        entries = [
            _normalize_carpaint_entry(item, fallback_id=f"paint-{idx}")
            for idx, item in enumerate(data)
            if isinstance(item, dict)
        ]
        return _normalize_entries(entries)

    if isinstance(data, dict):
        for key in ("carpaints", "paints", "materials", "entries"):
            value = data.get(key)
            if isinstance(value, list):
                entries = [
                    _normalize_carpaint_entry(item, fallback_id=f"paint-{idx}")
                    for idx, item in enumerate(value)
                    if isinstance(item, dict)
                ]
                return _normalize_entries(entries)

        if data and all(isinstance(value, dict) for value in data.values()):
            entries = [
                _normalize_carpaint_entry(value, fallback_id=str(key))
                for key, value in data.items()
            ]
            return _normalize_entries(entries)

    raise ValueError("Unsupported carpaints format")


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    shared: list[str] = []
    for item in root.findall("main:si", SPREADSHEET_NS):
        text = "".join(node.text or "" for node in item.iterfind(".//main:t", SPREADSHEET_NS))
        shared.append(text)
    return shared


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relationships
    }

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("main:sheets/main:sheet", SPREADSHEET_NS):
        sheet_name = sheet.attrib["name"]
        target = rel_targets[sheet.attrib[WORKBOOK_REL_NS]]
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        sheets.append((sheet_name, target))
    return sheets


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        value = "".join(node.text or "" for node in cell.iterfind(".//main:t", SPREADSHEET_NS))
        return value or None

    node = cell.find("main:v", SPREADSHEET_NS)
    if node is None or node.text is None:
        return None

    if cell_type == "s":
        return shared_strings[int(node.text)]
    if cell_type == "str":
        return node.text

    numeric = _to_float(node.text)
    if numeric is None:
        return node.text
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _sheet_rows(archive: zipfile.ZipFile, target: str, shared_strings: list[str]) -> list[dict[str, Any]]:
    root = ET.fromstring(archive.read(target))
    rows: list[dict[str, Any]] = []
    for row in root.findall("main:sheetData/main:row", SPREADSHEET_NS):
        values: dict[str, Any] = {}
        for cell in row.findall("main:c", SPREADSHEET_NS):
            reference = cell.attrib.get("r", "")
            column = "".join(character for character in reference if character.isalpha())
            if not column:
                continue
            values[column] = _cell_text(cell, shared_strings)
        if values:
            rows.append(values)
    return rows


def _workbook_row_to_entry(sheet_name: str, row: dict[str, Any]) -> dict[str, Any] | None:
    code = row.get("A")
    name = row.get("B")
    if code in (None, ""):
        return None

    legacy_entry: dict[str, Any] = {
        "Code": code,
        "name": name or str(code),
        "Brand": row.get("G"),
    }

    full_layout_base = [row.get("K"), row.get("L"), row.get("M")]
    compact_layout_base = [row.get("C"), row.get("D"), row.get("E")]
    looks_like_full_layout = row.get("W") is not None or any(
        row.get(column) is not None for column in ("P", "Q", "R", "S", "T", "U", "V")
    )
    looks_like_compact_layout = row.get("O") is not None or any(
        row.get(column) is not None for column in ("C", "D", "E", "F", "G", "H", "I", "J", "N")
    )

    if looks_like_full_layout and any(value is not None for value in full_layout_base):
        legacy_entry["BaseColor"] = full_layout_base
        legacy_entry["HalftoneColor"] = [row.get("N"), row.get("O"), row.get("P")]
        legacy_entry["ShadowTint"] = [row.get("Q"), row.get("R"), row.get("S")]
        legacy_entry["HighlightTint"] = [row.get("T"), row.get("U"), row.get("V")]
        legacy_entry["StyleID"] = row.get("W")
    elif looks_like_compact_layout and any(value is not None for value in compact_layout_base):
        legacy_entry["BaseColor"] = compact_layout_base
        legacy_entry["HalftoneColor"] = [row.get("F"), row.get("G"), row.get("H")]
        legacy_entry["ShadowTint"] = [row.get("I"), row.get("J"), row.get("K")]
        legacy_entry["HighlightTint"] = [row.get("L"), row.get("M"), row.get("N")]
        legacy_entry["StyleID"] = row.get("O")

    normalized = _normalize_carpaint_entry(
        legacy_entry,
        fallback_id=str(code),
        source_format="xlsx_workbook",
        sheet=sheet_name,
    )
    if "base_color" not in normalized:
        return None
    return normalized


def _load_workbook_carpaints(path: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        shared_strings = _load_shared_strings(archive)
        for sheet_name, target in _sheet_targets(archive):
            for row in _sheet_rows(archive, target, shared_strings):
                entry = _workbook_row_to_entry(sheet_name, row)
                if entry is not None:
                    entries.append(entry)
    return _normalize_entries(entries)


def _looks_like_legacy_payload(data: Any) -> bool:
    if isinstance(data, list):
        return any(isinstance(item, dict) and _is_legacy_entry(item) for item in data)
    if isinstance(data, dict):
        for key in ("carpaints", "paints", "materials", "entries"):
            value = data.get(key)
            if isinstance(value, list):
                return any(isinstance(item, dict) and _is_legacy_entry(item) for item in value)
        return any(isinstance(value, dict) and _is_legacy_entry(value) for value in data.values())
    return False


def _choose_carpaints_input(path: Path, *, prefer_json: bool) -> Path:
    if path.is_file():
        return path
    if not path.exists():
        raise FileNotFoundError(f"Input path does not exist: {path}")

    patterns = []
    if not prefer_json:
        patterns.extend(["*carpaint*.xlsx", "*paint*.xlsx", "*.xlsx"])
    patterns.extend(["*carpaint*.json", "*paint*.json", "*.json"])
    if prefer_json:
        patterns.extend(["*carpaint*.xlsx", "*paint*.xlsx", "*.xlsx"])

    matches = find_matches(path, patterns, limit=1)
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No carpaint input file found under: {path}")


def normalize_carpaints_source(
    path: Path,
    *,
    helper_path: Path | None = None,
) -> tuple[dict[str, Any], str | None]:
    source_path = _choose_carpaints_input(path, prefer_json=helper_path is not None)

    note: str | None = None
    if source_path.suffix.lower() == ".xlsx":
        note = (
            "Carpaint workbook parsed via built-in XLSX adapter; finish, roughness, "
            "metallic, and clearcoat were inferred heuristically because workbook-style "
            "sources only expose legacy paint fields. Rows without usable base-color "
            "payload were skipped."
        )
        return _load_workbook_carpaints(source_path), note

    if helper_path is not None:
        try:
            payload = _load_via_helper(helper_path.resolve(), source_path.resolve())
            return normalize_carpaints_payload(payload), None
        except Exception as exc:
            note = (
                f"Carpaint helper {helper_path.resolve()} could not be executed as a JSON adapter; "
                f"fell back to raw JSON input. Reason: {exc}"
            )

    raw_payload = load_json(source_path)
    if _looks_like_legacy_payload(raw_payload):
        legacy_note = (
            "Legacy SG-style carpaint JSON was normalized; finish, roughness, metallic, and "
            "clearcoat were inferred heuristically from available name/style data."
        )
        note = f"{note} {legacy_note}".strip() if note else legacy_note

    return normalize_carpaints_payload(raw_payload), note
