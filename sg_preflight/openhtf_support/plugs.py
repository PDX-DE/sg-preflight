from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.manual_review import MANUAL_REVIEW_HEADER, QUALITY_HERO_STEPS

from .dependency import require_openhtf


htf = require_openhtf()


@dataclass(frozen=True)
class SgfxStationContext:
    profile_id: str
    workspace: Path
    bmw_root: Path | None = None
    ui_mode: str = "clean"

    def as_payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "workspace": str(self.workspace),
            "bmw_root": str(self.bmw_root) if self.bmw_root else "",
            "ui_mode": self.ui_mode,
            "read_only": True,
            "manual_review_required": True,
            "is_approval": False,
        }


_ACTIVE_CONTEXT = SgfxStationContext(profile_id="G65", workspace=Path.cwd())


def configure_sgfx_context(context: SgfxStationContext) -> None:
    global _ACTIVE_CONTEXT
    _ACTIVE_CONTEXT = context


def active_context() -> SgfxStationContext:
    return _ACTIVE_CONTEXT


class SgfxContextPlug(htf.BasePlug):
    def context(self) -> SgfxStationContext:
        return active_context()

    def payload(self) -> dict[str, Any]:
        return self.context().as_payload()

    def read_daily_digest(self) -> dict[str, Any]:
        from sg_preflight.daily_digest import build_latest_daily_digest

        context = active_context()
        return build_latest_daily_digest(workspace=context.workspace)


class WorkbookEvidencePlug(htf.BasePlug):
    def read_delivery_checklist(self) -> dict[str, Any]:
        from sg_preflight.delivery_checklist import read_delivery_checklist

        context = active_context()
        return read_delivery_checklist(profile_id=context.profile_id, workspace=context.workspace)


class BmwGitMirrorPlug(htf.BasePlug):
    def read_screenshot_test_state(self) -> dict[str, Any]:
        from sg_preflight.bmw_delivery import read_bmw_screenshot_state

        context = active_context()
        return read_bmw_screenshot_state(context.profile_id, workspace=context.workspace)


class ManualReviewPlug(htf.BasePlug):
    def manual_review_companion(self) -> dict[str, Any]:
        context = active_context()
        step_titles = [step.title for step in QUALITY_HERO_STEPS]
        return {
            "profile_id": context.profile_id,
            "status": "not_run",
            "data_available": False,
            "summary": f"{len(step_titles)} Quality-Hero manual-review step(s) are ready for operator recording.",
            "header": MANUAL_REVIEW_HEADER,
            "step_count": len(step_titles),
            "steps": step_titles,
            "note": "Manual review remains required; this phase only prepares the companion checklist.",
            "is_approval": False,
        }
