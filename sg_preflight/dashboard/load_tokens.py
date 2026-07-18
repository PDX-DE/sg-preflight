"""Dashboard page/snapshot load tokens, NiceGUI poll-timer helpers, and the
runtime-error classifiers used to tell a harmless UI teardown race from a
real bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class DashboardLoadToken:
    generation: int
    profile_id: str
    page_id: str


def _dashboard_load_token_matches(
    token: DashboardLoadToken,
    *,
    generation: int,
    profile_id: str,
    page_id: str,
) -> bool:
    return token == DashboardLoadToken(generation, profile_id, page_id)


def _next_dashboard_load_token(
    state: dict[str, Any],
    *,
    profile_id: str,
    page_id: str,
    reason: str,
) -> DashboardLoadToken:
    if reason not in {"navigation", "profile_change", "refresh"}:
        raise ValueError(f"Unsupported dashboard load invalidation reason: {reason}")
    generation = int(state.get("load_generation", 0)) + 1
    state["load_generation"] = generation
    state["requested_profile_id"] = str(profile_id)
    state["active_page_id"] = str(page_id)
    return DashboardLoadToken(generation, str(profile_id), str(page_id))


def _dashboard_load_token_is_current(token: DashboardLoadToken, state: dict[str, Any]) -> bool:
    return _dashboard_load_token_matches(
        token,
        generation=int(state.get("load_generation", 0)),
        profile_id=str(state.get("requested_profile_id", "")),
        page_id=str(state.get("active_page_id", "")),
    )


def _complete_dashboard_page_load(
    token: DashboardLoadToken,
    *,
    state: dict[str, Any],
    page: dict[str, Any] | None,
    error: Exception | None,
    render_current_page: Callable[[], None],
    notify: Callable[[str], None],
    finish_transition: Callable[[str], None],
    transition_page_id: str = "",
    notify_message: str = "",
) -> bool:
    if not _dashboard_load_token_is_current(token, state):
        return False
    if error is not None:
        state["loading_message"] = ""
        render_current_page()
        finish_transition(transition_page_id)
        notify(f"Page load failed: {error}")
        return True
    if page is None:
        raise ValueError("Dashboard page completion requires a page or an error")
    snapshot = state.get("snapshot", {})
    pages = snapshot.get("pages", []) if isinstance(snapshot, dict) else []
    updated_pages = [
        page if str(existing.get("id", "")) == token.page_id else existing
        for existing in pages
        if isinstance(existing, dict)
    ]
    state["snapshot"] = {**snapshot, "pages": updated_pages}
    state["loading_message"] = ""
    render_current_page()
    finish_transition(transition_page_id)
    if notify_message:
        notify(notify_message)
    return True


def _complete_dashboard_snapshot_refresh(
    token: DashboardLoadToken,
    *,
    state: dict[str, Any],
    snapshot: dict[str, Any] | None,
    error: Exception | None,
    render_current_page: Callable[[], None],
    refresh_labels: Callable[[], None],
    notify: Callable[[str], None],
    finish_transition: Callable[[str], None],
    transition_page_id: str = "",
    notify_message: str = "",
) -> bool:
    if not _dashboard_load_token_is_current(token, state):
        return False
    if error is not None:
        state["loading_message"] = ""
        render_current_page()
        finish_transition(transition_page_id)
        notify(f"Dashboard refresh failed: {error}")
        return True
    if snapshot is None:
        raise ValueError("Dashboard snapshot completion requires a snapshot or an error")
    state["snapshot"] = snapshot
    state["requested_profile_id"] = str(snapshot.get("profile_id", token.profile_id))
    state["loading_message"] = ""
    refresh_labels()
    render_current_page()
    finish_transition(transition_page_id)
    if notify_message:
        notify(notify_message)
    return True


def _start_background_poll_timer(interval: float, callback: Callable[[], None]) -> Any:
    from nicegui.timer import Timer

    return Timer(interval, callback, active=True, immediate=False)


def _start_io_bound_poll_timer(
    interval: float,
    poll_fn: Callable[[], Any],
    apply_fn: Callable[[Any], None],
    error_fn: Callable[[Exception], None] | None = None,
) -> Any:
    from nicegui import run as nicegui_run
    from nicegui.timer import Timer

    async def _tick() -> None:
        try:
            result = await nicegui_run.io_bound(poll_fn)
        except Exception as exc:  # noqa: BLE001
            if error_fn is not None:
                error_fn(exc)
                return
            raise
        apply_fn(result)

    return Timer(interval, _tick, active=True, immediate=False)


def _cancel_background_poll_timer(timer: Any) -> None:
    if timer is None:
        return
    try:
        timer.cancel(with_current_invocation=True)
    except TypeError:
        timer.cancel()
    except RuntimeError:
        return


def _parent_slot_deleted(error: RuntimeError) -> bool:
    message = str(error).casefold()
    return ("parent slot" in message or ("parent element" in message and "slot" in message)) and "deleted" in message


def _nicegui_client_deleted(error: RuntimeError) -> bool:
    message = str(error).casefold()
    return "client this element belongs to has been deleted" in message


def _ignorable_nicegui_runtime_error(error: RuntimeError) -> bool:
    message = str(error).casefold()
    return _parent_slot_deleted(error) or _nicegui_client_deleted(error) or (
        "current slot cannot be determined" in message and "slot stack" in message
    )


def _run_javascript_if_client_alive(ui: Any, code: str) -> None:
    try:
        ui.run_javascript(code)
    except RuntimeError as exc:
        if not _ignorable_nicegui_runtime_error(exc):
            raise
