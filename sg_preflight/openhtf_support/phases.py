from __future__ import annotations

from typing import Any

from .outcomes import openhtf_phase_result, phase_payload, sgfx_status_from_payload


QUALITY_HERO_ANCHOR = (
    "confluence-readable-dumps/PDX_"
    + "SER"
    + "GFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt"
)
SG_DAILY_ANCHOR = (
    "confluence-readable-dumps/PDX_"
    + "SER"
    + "GFX/016_Project-Management/024_How-to...-Seriesgraphics/029_Regular-Meetings/030_SG-Daily/page.txt"
)


def _summary(payload: dict[str, Any], fallback: str) -> str:
    for key in ("summary", "no_data_message", "message"):
        value = str(payload.get(key, "")).strip()
        if value:
            return value
    return fallback


def _observation(
    *,
    phase_id: str,
    source: str,
    payload: dict[str, Any],
    fallback_summary: str,
    confluence_anchor: str,
) -> dict[str, Any]:
    return phase_payload(
        phase_id=phase_id,
        source=source,
        sgfx_status=sgfx_status_from_payload(payload),
        summary=_summary(payload, fallback_summary),
        raw_payload=payload,
        confluence_anchor=confluence_anchor,
    )


def build_delivery_checklist_observation(context: Any, workbook: Any) -> dict[str, Any]:
    return _observation(
        phase_id="delivery_checklist_phase",
        source="delivery_checklist",
        payload=workbook.read_delivery_checklist(),
        fallback_summary=f"Delivery checklist state for {context.profile_id}.",
        confluence_anchor=QUALITY_HERO_ANCHOR,
    )


def build_screenshot_test_state_observation(context: Any, mirror: Any) -> dict[str, Any]:
    return _observation(
        phase_id="screenshot_test_state_phase",
        source="screenshot_test_state",
        payload=mirror.read_screenshot_test_state(),
        fallback_summary=f"Screenshot test state for {context.profile_id}.",
        confluence_anchor=QUALITY_HERO_ANCHOR,
    )


def build_daily_digest_observation(context: Any, daily: Any) -> dict[str, Any]:
    return _observation(
        phase_id="daily_digest_phase",
        source="daily_digest",
        payload=daily.read_daily_digest(),
        fallback_summary=f"Daily digest state for {context.profile_id}.",
        confluence_anchor=SG_DAILY_ANCHOR,
    )


def build_manual_review_companion_observation(context: Any, manual: Any) -> dict[str, Any]:
    return _observation(
        phase_id="manual_review_companion_phase",
        source="manual_review_companion",
        payload=manual.manual_review_companion(),
        fallback_summary=f"Manual review companion for {context.profile_id}.",
        confluence_anchor=QUALITY_HERO_ANCHOR,
    )


def _write_measurements(test: Any, observation: dict[str, Any]) -> None:
    test.measurements.sgfx_status = observation["sgfx_status"]
    test.measurements.sgfx_source = observation["source"]
    test.measurements.sgfx_summary = observation["summary"]


def make_openhtf_phases() -> tuple[Any, ...]:
    from .dependency import require_openhtf
    from .plugs import BmwGitMirrorPlug, ManualReviewPlug, SgfxContextPlug, WorkbookEvidencePlug

    htf = require_openhtf()

    @htf.PhaseOptions(name="delivery_checklist_phase")
    @htf.plug(context=SgfxContextPlug, workbook=WorkbookEvidencePlug)
    @htf.measures("sgfx_status", "sgfx_source", "sgfx_summary")
    def delivery_checklist_phase(test: Any, context: SgfxContextPlug, workbook: WorkbookEvidencePlug) -> Any:
        observation = build_delivery_checklist_observation(context.context(), workbook)
        _write_measurements(test, observation)
        return openhtf_phase_result(str(observation["sgfx_status"]), htf)

    @htf.PhaseOptions(name="screenshot_test_state_phase")
    @htf.plug(context=SgfxContextPlug, mirror=BmwGitMirrorPlug)
    @htf.measures("sgfx_status", "sgfx_source", "sgfx_summary")
    def screenshot_test_state_phase(test: Any, context: SgfxContextPlug, mirror: BmwGitMirrorPlug) -> Any:
        observation = build_screenshot_test_state_observation(context.context(), mirror)
        _write_measurements(test, observation)
        return openhtf_phase_result(str(observation["sgfx_status"]), htf)

    @htf.PhaseOptions(name="daily_digest_phase")
    @htf.plug(context=SgfxContextPlug)
    @htf.measures("sgfx_status", "sgfx_source", "sgfx_summary")
    def daily_digest_phase(test: Any, context: SgfxContextPlug) -> Any:
        observation = build_daily_digest_observation(context.context(), context)
        _write_measurements(test, observation)
        return openhtf_phase_result(str(observation["sgfx_status"]), htf)

    @htf.PhaseOptions(name="manual_review_companion_phase")
    @htf.plug(context=SgfxContextPlug, manual=ManualReviewPlug)
    @htf.measures("sgfx_status", "sgfx_source", "sgfx_summary")
    def manual_review_companion_phase(test: Any, context: SgfxContextPlug, manual: ManualReviewPlug) -> Any:
        observation = build_manual_review_companion_observation(context.context(), manual)
        _write_measurements(test, observation)
        return openhtf_phase_result(str(observation["sgfx_status"]), htf)

    return (
        delivery_checklist_phase,
        screenshot_test_state_phase,
        daily_digest_phase,
        manual_review_companion_phase,
    )
