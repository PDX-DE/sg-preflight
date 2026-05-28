from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsOpacityEffect,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from sg_preflight.assets import runtime_asset_path
from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.desktop_notifications import notify_desktop_completion
from sg_preflight.desktop.evidence_model import (
    DesktopActionChoice,
    DesktopActionSnapshot,
    DesktopEvidenceItem,
    desktop_action_snapshot,
    desktop_actions_for_profile,
    desktop_blocker_items,
    desktop_manual_cards,
    desktop_profiles,
    desktop_surface_items,
    latest_action_snapshot_for_profile,
)
from sg_preflight.desktop.file_ops import open_local_path, reveal_in_file_manager
from sg_preflight.desktop.widgets import (
    ActionTabButton,
    GuideButton,
    HeaderBanner,
    OperatorChrome,
    StaticListWidget,
    OperatorPanel,
)
from sg_preflight.desktop.workers import ActionRunner
from sg_preflight.dependency_onboarding import (
    DependencySetupJob,
    build_dependency_onboarding_status,
    cancel_dependency_setup_action,
    poll_dependency_setup_action,
    start_dependency_setup_action,
)
from sg_preflight.profiles import get_run_profile
from sg_preflight.qa_actions import build_action_record, get_operator_action
from sg_preflight.screenshot_review_viewer import build_screenshot_review_viewer
from sg_preflight.services import operator_ui_root, workspace_root
from sg_preflight.visual_review import build_visual_review_prep


GRAFIKS_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)

GRAFIKS_WIP_NOTICE = "Grafiks mode is experimental — recommend Clean mode for daily work."
DESKTOP_WINDOW_TITLE = "Seriengrafik: Project Quality-Hero"
GRAFIKS_HOTKEY_MESSAGES = {
    Qt.Key_F1: ("F1", "Help: inspect local evidence surfaces, setup status, and guardrails."),
    Qt.Key_F2: ("F2", "Profile switch: focus the profile list."),
    Qt.Key_F3: ("F3", "Reference: no action is assigned to F3 in this release."),
    Qt.Key_F4: ("F4", "Reference: no action is assigned to F4 in this release."),
    Qt.Key_F5: ("F5", "Refresh: re-read setup status and current profile evidence."),
    Qt.Key_F6: ("F6", "Reference: no action is assigned to F6 in this release."),
    Qt.Key_F7: ("F7", "Reference: no action is assigned to F7 in this release."),
    Qt.Key_F8: ("F8", "Reference: no action is assigned to F8 in this release."),
    Qt.Key_F9: ("F9", "Reference: no action is assigned to F9 in this release."),
    Qt.Key_F10: ("F10", "Reference: no action is assigned to F10 in this release."),
    Qt.Key_F11: ("F11", "Reference: no action is assigned to F11 in this release."),
    Qt.Key_F12: ("F12", "Diagnostic: current profile, mode, and workspace stay local."),
    Qt.Key_Escape: ("Esc", "Quit guidance: close the window when the local review is done."),
}
_SETUP_SOURCE_REQUIRED = {"setup-raco-from-shared-tools", "setup-blender-411"}
_SETUP_TARGET_REQUIRED = {
    "setup-raco-from-shared-tools",
    "clone-digital-3d-car-repo",
    "setup-digital-3d-car-repo",
}


def _clean_presentation_mode(value: str | None) -> str:
    normalized = str(value or "clean").strip().casefold()
    return normalized if normalized in {"clean", "grafiks"} else "clean"


class DesktopMainWindow(QMainWindow):
    switch_requested = Signal(str)

    def __init__(self, *, workspace: Path | None = None, initial_profile_id: str = "", initial_mode: str = "clean") -> None:
        super().__init__()
        self.workspace_root = workspace_root(workspace)
        self.initial_profile_id = initial_profile_id.strip().upper()
        self.presentation_mode = _clean_presentation_mode(initial_mode)
        self._runner: ActionRunner | None = None
        self._current_run_id = ""
        self._current_snapshot: DesktopActionSnapshot | None = None
        self._copy_map: dict[str, str] = {}
        self._action_tab_buttons: dict[str, ActionTabButton] = {}
        self._setup_status: dict[str, Any] = {}
        self._setup_actions: list[dict[str, Any]] = []
        self._setup_job: DependencySetupJob | None = None
        self._hotkey_animation: QPropertyAnimation | None = None
        self._hotkey_popup: QWidget | None = None
        self._hotkey_icon_label: QLabel | None = None
        self._hotkey_text_label: QLabel | None = None
        self._hotkey_opacity: QGraphicsOpacityEffect | None = None
        self._hotkey_icon_pixmap = QPixmap(str(runtime_asset_path("debug_icon.png")))
        self._hotkey_pulse_step = 0
        self._screenshot_review_dialog: QDialog | None = None

        icon_path = runtime_asset_path("desktop_native/resources/exe_ico.ico")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1640, 950)
        self._build_ui()
        self._set_presentation_mode(self.presentation_mode)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(800)
        self._poll_timer.timeout.connect(self._poll_current_action)
        self._setup_poll_timer = QTimer(self)
        self._setup_poll_timer.setInterval(1000)
        self._setup_poll_timer.timeout.connect(self._poll_dependency_setup)
        self._reload_profiles()

    def _build_ui(self) -> None:
        central = OperatorChrome(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(10)

        self.header_banner = HeaderBanner(
            "",
            "",
            central,
            logo_path=runtime_asset_path("logo_sgfx.png"),
        )
        layout.addWidget(self.header_banner)

        self.wip_notice = QLabel(GRAFIKS_WIP_NOTICE, central)
        self.wip_notice.setObjectName("grafiksWipNotice")
        self.wip_notice.setWordWrap(True)
        self.wip_notice.setVisible(False)
        layout.addWidget(self.wip_notice)

        self.mode_panel = OperatorPanel("Mode Select", central)
        mode_layout = QVBoxLayout(self.mode_panel)
        mode_layout.setSpacing(8)
        mode_label = QLabel("Recommended SG action tabs for the selected live slice.")
        mode_label.setObjectName("modeLabel")
        mode_layout.addWidget(mode_label)

        self.presentation_toggle_host = QWidget(self.mode_panel)
        presentation_toggle_layout = QHBoxLayout(self.presentation_toggle_host)
        presentation_toggle_layout.setContentsMargins(0, 0, 0, 0)
        presentation_toggle_layout.setSpacing(6)
        self.clean_mode_button = QPushButton("Clean", self.presentation_toggle_host)
        self.grafiks_mode_button = QPushButton("Grafiks", self.presentation_toggle_host)
        for button in (self.clean_mode_button, self.grafiks_mode_button):
            button.setCheckable(True)
            button.setMinimumHeight(30)
            button.setMinimumWidth(96)
            button.setObjectName("presentationToggle")
        self.clean_mode_button.clicked.connect(lambda: self._request_presentation_mode("clean"))
        self.grafiks_mode_button.clicked.connect(lambda: self._request_presentation_mode("grafiks"))
        presentation_toggle_layout.addWidget(self.clean_mode_button)
        presentation_toggle_layout.addWidget(self.grafiks_mode_button)
        presentation_toggle_layout.addStretch(1)
        mode_layout.addWidget(self.presentation_toggle_host)

        self.action_tab_host = QWidget(self.mode_panel)
        self.action_tab_layout = QHBoxLayout(self.action_tab_host)
        self.action_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.action_tab_layout.setSpacing(8)
        mode_layout.addWidget(self.action_tab_host)
        layout.addWidget(self.mode_panel)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self._build_left_column())
        splitter.addWidget(self._build_center_column())
        splitter.addWidget(self._build_right_column())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 3)
        layout.addWidget(splitter, stretch=1)

        bottom = QWidget(self)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        self.run_button = GuideButton("A", "Run", bottom)
        self.run_button.clicked.connect(self._run_selected_action)
        bottom_layout.addWidget(self.run_button)

        self.open_file_button = GuideButton("X", "Open File", bottom)
        self.open_file_button.clicked.connect(self._open_selected_evidence)
        bottom_layout.addWidget(self.open_file_button)

        self.reveal_button = GuideButton("Y", "Reveal", bottom)
        self.reveal_button.clicked.connect(self._reveal_selected_evidence)
        bottom_layout.addWidget(self.reveal_button)

        self.open_log_button = GuideButton("LB", "Open Log", bottom)
        self.open_log_button.clicked.connect(self._open_log)
        bottom_layout.addWidget(self.open_log_button)

        self.open_report_button = GuideButton("RB", "Open Report", bottom)
        self.open_report_button.clicked.connect(self._open_latest_report)
        bottom_layout.addWidget(self.open_report_button)

        self.open_evidence_button = GuideButton("RT", "Open Evidence", bottom)
        self.open_evidence_button.clicked.connect(self._open_latest_evidence)
        bottom_layout.addWidget(self.open_evidence_button)

        self.screenshot_review_button = GuideButton("LT", "Diff Viewer", bottom)
        self.screenshot_review_button.clicked.connect(self._open_screenshot_review_viewer)
        bottom_layout.addWidget(self.screenshot_review_button)

        self.copy_jira_button = GuideButton("J", "Copy Jira", bottom)
        self.copy_jira_button.clicked.connect(lambda: self._copy_text("jira"))
        bottom_layout.addWidget(self.copy_jira_button)

        self.copy_qa_hero_button = GuideButton("Q", "Copy QA Hero", bottom)
        self.copy_qa_hero_button.clicked.connect(lambda: self._copy_text("qa_hero"))
        bottom_layout.addWidget(self.copy_qa_hero_button)

        self.copy_handoff_button = GuideButton("H", "Copy Handoff", bottom)
        self.copy_handoff_button.clicked.connect(lambda: self._copy_text("handoff"))
        bottom_layout.addWidget(self.copy_handoff_button)

        self.about_button = GuideButton("F1", "About", bottom)
        self.about_button.clicked.connect(self._show_about_dialog)
        bottom_layout.addWidget(self.about_button)

        layout.addWidget(bottom)

        guardrail_panel = OperatorPanel("Standing Guardrails", central)
        guardrail_layout = QVBoxLayout(guardrail_panel)
        guardrail_layout.setSpacing(2)
        for guardrail in GRAFIKS_GUARDRAILS:
            label = QLabel(guardrail, guardrail_panel)
            label.setObjectName("panelHint")
            label.setWordWrap(True)
            guardrail_layout.addWidget(label)
        layout.addWidget(guardrail_panel)

        self.setCentralWidget(central)

        status = QStatusBar(self)
        self.setStatusBar(status)
        self._install_static_tooltips()
        self._build_hotkey_popup()

    def _install_static_tooltips(self) -> None:
        self.header_banner.setToolTip("Current SGFX profile context and local evidence workspace.")
        self.wip_notice.setToolTip("Grafiks is experimental; Clean mode remains recommended for daily work.")
        self.mode_panel.setToolTip("Switch between Clean embedded dashboard and Grafiks shell.")
        self.clean_mode_button.setToolTip("Open the embedded Clean view.")
        self.grafiks_mode_button.setToolTip("Stay in the experimental Grafiks shell.")
        self.profile_list.setToolTip("Select the local delivery profile to inspect.")
        self.action_list.setToolTip("Choose the operator action for the selected profile.")
        self.run_button.setToolTip("Run the selected local action.")
        self.open_file_button.setToolTip("Open the selected evidence file.")
        self.reveal_button.setToolTip("Reveal the selected evidence path in the file manager.")
        self.open_log_button.setToolTip("Open the latest action log for the current run.")
        self.open_report_button.setToolTip("Open the latest HTML report when available.")
        self.open_evidence_button.setToolTip("Open the latest evidence bundle folder when available.")
        self.screenshot_review_button.setToolTip("Build and open the synchronized expected / actual / diff screenshot viewer.")
        self.copy_jira_button.setToolTip("Copy the prepared Jira note text to the clipboard.")
        self.copy_qa_hero_button.setToolTip("Copy the prepared QA Hero note text to the clipboard.")
        self.copy_handoff_button.setToolTip("Copy the local handoff text to the clipboard.")
        self.about_button.setToolTip("Open the About panel and documented local-evidence guardrails.")
        self.evidence_list.setToolTip("Evidence paths from the current action snapshot.")
        self.setup_list.setToolTip("Dependency status rows prefer detected local installs before fallback setup.")
        self.setup_action_selector.setToolTip("Select a confirmation-gated setup action.")
        self.setup_run_button.setToolTip("Run setup only after reviewing the confirmation dialog.")
        self.setup_cancel_button.setToolTip("Cancel the currently running setup worker.")
        self.setup_output.setToolTip("Live setup output and file activity from the local worker.")
        self.surface_list.setToolTip("Evidence surfaces available for the selected profile.")
        self.blocker_list.setToolTip("Local blockers that require operator attention.")
        self.manual_list.setToolTip("Manual-review companion status; review remains required.")

    def _build_hotkey_popup(self) -> None:
        popup = QWidget(self)
        popup.setObjectName("hotkeyPopup")
        popup.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup.setStyleSheet(
            """
QWidget#hotkeyPopup {
  background: rgba(18, 27, 31, 245);
  border: 1px solid #4ec9b0;
  border-radius: 8px;
}
QLabel#hotkeyText {
  color: #d4d4d4;
  font-family: "Segoe UI", "Bahnschrift", sans-serif;
  font-size: 13px;
}
"""
        )
        popup_layout = QHBoxLayout(popup)
        popup_layout.setContentsMargins(14, 12, 16, 12)
        popup_layout.setSpacing(14)

        icon_label = QLabel(popup)
        icon_label.setFixedSize(104, 104)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        popup_layout.addWidget(icon_label)

        text_label = QLabel("F1\nShortcuts available.", popup)
        text_label.setObjectName("hotkeyText")
        text_label.setWordWrap(True)
        text_label.setMinimumWidth(240)
        popup_layout.addWidget(text_label)

        opacity = QGraphicsOpacityEffect(popup)
        opacity.setOpacity(0.0)
        popup.setGraphicsEffect(opacity)
        popup.hide()

        self._hotkey_popup = popup
        self._hotkey_icon_label = icon_label
        self._hotkey_text_label = text_label
        self._hotkey_opacity = opacity
        self._hotkey_hide_timer = QTimer(self)
        self._hotkey_hide_timer.setSingleShot(True)
        self._hotkey_hide_timer.timeout.connect(self._fade_hotkey_popup)
        self._hotkey_pulse_timer = QTimer(self)
        self._hotkey_pulse_timer.setInterval(110)
        self._hotkey_pulse_timer.timeout.connect(self._pulse_hotkey_icon)

    def _place_hotkey_popup(self) -> None:
        if self._hotkey_popup is None:
            return
        self._hotkey_popup.adjustSize()
        margin = 32
        x = max(margin, self.width() - self._hotkey_popup.width() - margin)
        self._hotkey_popup.move(x, 82)

    def _set_hotkey_icon_size(self, size: int) -> None:
        if self._hotkey_icon_label is None or self._hotkey_icon_pixmap.isNull():
            return
        pixmap = self._hotkey_icon_pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._hotkey_icon_label.setPixmap(pixmap)

    def _pulse_hotkey_icon(self) -> None:
        self._hotkey_pulse_step = (self._hotkey_pulse_step + 1) % 12
        distance = abs(6 - self._hotkey_pulse_step)
        self._set_hotkey_icon_size(88 + (6 - distance) * 2)

    def _animate_hotkey_opacity(self, start: float, end: float, duration: int) -> QPropertyAnimation | None:
        if self._hotkey_opacity is None:
            return None
        if self._hotkey_animation is not None:
            self._hotkey_animation.stop()
        animation = QPropertyAnimation(self._hotkey_opacity, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hotkey_animation = animation
        animation.start()
        return animation

    def _show_hotkey_popup(self, key_label: str, message: str) -> None:
        if self._hotkey_popup is None or self._hotkey_text_label is None:
            return
        self._hotkey_text_label.setText(f"{key_label}\n{message}")
        self._set_hotkey_icon_size(96)
        self._place_hotkey_popup()
        self._hotkey_popup.show()
        self._hotkey_popup.raise_()
        self._hotkey_pulse_timer.start()
        self._animate_hotkey_opacity(0.0, 1.0, 150)
        self._hotkey_hide_timer.start(1100)

    def _fade_hotkey_popup(self) -> None:
        animation = self._animate_hotkey_opacity(1.0, 0.0, 250)
        if animation is None or self._hotkey_popup is None:
            return

        def _hide() -> None:
            if self._hotkey_popup is not None:
                self._hotkey_popup.hide()
            self._hotkey_pulse_timer.stop()

        animation.finished.connect(_hide)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._hotkey_popup is not None and self._hotkey_popup.isVisible():
            self._place_hotkey_popup()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        hotkey = GRAFIKS_HOTKEY_MESSAGES.get(event.key())
        if hotkey is None:
            super().keyPressEvent(event)
            return
        key_label, message = hotkey
        if event.key() == Qt.Key_F2:
            self.profile_list.setFocus()
        elif event.key() == Qt.Key_F5:
            profile_id = self._current_profile_id()
            self._reload_side_panels(profile_id)
            self._load_latest_snapshot(profile_id)
        elif event.key() == Qt.Key_F12:
            message = f"{message} Profile: {self._current_profile_id() or 'unknown'}; mode: {self.presentation_mode}."
        self._show_hotkey_popup(key_label, message)
        event.accept()

    def _request_presentation_mode(self, mode: str) -> None:
        normalized = _clean_presentation_mode(mode)
        if normalized == self.presentation_mode:
            self._set_presentation_mode(normalized)
            return
        self.switch_requested.emit(normalized)

    def _set_presentation_mode(self, mode: str) -> None:
        self.presentation_mode = _clean_presentation_mode(mode)
        is_clean = self.presentation_mode == "clean"
        self.setWindowTitle(DESKTOP_WINDOW_TITLE)
        self.clean_mode_button.setChecked(is_clean)
        self.grafiks_mode_button.setChecked(not is_clean)
        self.wip_notice.setVisible(not is_clean)
        self.statusBar().showMessage("local evidence only")
        self._apply_presentation_property()
        self.header_banner.update()

    def _apply_presentation_property(self) -> None:
        widgets = [self, self.centralWidget(), self.statusBar(), *self.findChildren(QWidget)]
        for widget in widgets:
            if widget is None:
                continue
            widget.setProperty("sgfxMode", self.presentation_mode)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _build_left_column(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        profiles_box = OperatorPanel("Profiles", widget)
        profiles_layout = QVBoxLayout(profiles_box)
        self.profile_detail = QLabel("Canonical live slices on the mirrored SG tree.")
        self.profile_detail.setObjectName("panelHint")
        profiles_layout.addWidget(self.profile_detail)
        self.profile_list = StaticListWidget(parent=profiles_box)
        self.profile_list.currentItemChanged.connect(self._profile_changed)
        self.profile_list.setMinimumWidth(320)
        profiles_layout.addWidget(self.profile_list)
        layout.addWidget(profiles_box, stretch=2)

        actions_box = OperatorPanel("Command Deck", widget)
        actions_layout = QVBoxLayout(actions_box)
        self.action_detail = QLabel("The selected tab and the command deck stay in sync.")
        self.action_detail.setObjectName("panelHint")
        actions_layout.addWidget(self.action_detail)
        self.action_list = StaticListWidget(parent=actions_box)
        self.action_list.currentItemChanged.connect(self._action_changed)
        self.action_list.setMinimumHeight(220)
        actions_layout.addWidget(self.action_list)
        layout.addWidget(actions_box, stretch=1)
        return widget

    def _build_center_column(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        run_box = OperatorPanel("Active Run / Result", widget)
        run_layout = QVBoxLayout(run_box)
        run_layout.setSpacing(10)

        self.run_title = QLabel("No action selected")
        self.run_title.setObjectName("runTitle")
        run_layout.addWidget(self.run_title)

        self.run_status = QLabel("Choose a profile and action.")
        self.run_status.setObjectName("runStatus")
        run_layout.addWidget(self.run_status)

        self.progress_bar = QProgressBar(run_box)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        run_layout.addWidget(self.progress_bar)

        self.progress_detail = QLabel("")
        self.progress_detail.setWordWrap(True)
        self.progress_detail.setObjectName("progressInfo")
        run_layout.addWidget(self.progress_detail)

        self.command_label = QLabel("")
        self.command_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.command_label.setWordWrap(True)
        self.command_label.setObjectName("commandLabel")
        run_layout.addWidget(self.command_label)

        summary_box = OperatorPanel("Summary", run_box)
        summary_layout = QVBoxLayout(summary_box)
        self.summary_text = QPlainTextEdit(summary_box)
        self.summary_text.setReadOnly(True)
        self.summary_text.setObjectName("summaryText")
        summary_layout.addWidget(self.summary_text)
        run_layout.addWidget(summary_box, stretch=2)

        log_box = OperatorPanel("Signal Log", run_box)
        log_layout = QVBoxLayout(log_box)
        self.log_tail = QPlainTextEdit(log_box)
        self.log_tail.setReadOnly(True)
        self.log_tail.setObjectName("logTail")
        log_layout.addWidget(self.log_tail)
        run_layout.addWidget(log_box, stretch=2)

        layout.addWidget(run_box, stretch=1)
        return widget

    def _build_right_column(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        evidence_box = OperatorPanel("Open First", widget)
        evidence_layout = QVBoxLayout(evidence_box)
        self.evidence_hint = QLabel("File-backed evidence panel for the first files to inspect.")
        self.evidence_hint.setObjectName("panelHint")
        evidence_layout.addWidget(self.evidence_hint)
        self.evidence_list = StaticListWidget(flash=True, parent=evidence_box)
        evidence_layout.addWidget(self.evidence_list)
        layout.addWidget(evidence_box, stretch=2)

        setup_box = OperatorPanel("Dependency Setup", widget)
        setup_layout = QVBoxLayout(setup_box)
        setup_layout.setSpacing(8)
        self.setup_status_label = QLabel("Dependency setup status not loaded.", setup_box)
        self.setup_status_label.setObjectName("panelHint")
        self.setup_status_label.setWordWrap(True)
        setup_layout.addWidget(self.setup_status_label)
        self.setup_list = StaticListWidget(parent=setup_box)
        self.setup_list.setMinimumHeight(120)
        setup_layout.addWidget(self.setup_list)
        self.setup_action_selector = QComboBox(setup_box)
        self.setup_action_selector.currentIndexChanged.connect(lambda _index: self._refresh_dependency_setup_buttons())
        setup_layout.addWidget(self.setup_action_selector)
        setup_buttons = QWidget(setup_box)
        setup_button_layout = QHBoxLayout(setup_buttons)
        setup_button_layout.setContentsMargins(0, 0, 0, 0)
        setup_button_layout.setSpacing(6)
        self.setup_run_button = QPushButton("Run Setup", setup_buttons)
        self.setup_run_button.clicked.connect(self._run_selected_dependency_setup)
        self.setup_cancel_button = QPushButton("Cancel Setup", setup_buttons)
        self.setup_cancel_button.clicked.connect(self._cancel_dependency_setup)
        setup_button_layout.addWidget(self.setup_run_button)
        setup_button_layout.addWidget(self.setup_cancel_button)
        setup_layout.addWidget(setup_buttons)
        self.setup_output = QPlainTextEdit(setup_box)
        self.setup_output.setReadOnly(True)
        self.setup_output.setObjectName("logTail")
        self.setup_output.setMaximumHeight(150)
        setup_layout.addWidget(self.setup_output)
        layout.addWidget(setup_box, stretch=2)

        surfaces_box = OperatorPanel("Evidence Surfaces", widget)
        surfaces_layout = QVBoxLayout(surfaces_box)
        self.surface_list = StaticListWidget(parent=surfaces_box)
        surfaces_layout.addWidget(self.surface_list)
        layout.addWidget(surfaces_box, stretch=1)

        blockers_box = OperatorPanel("Blockers", widget)
        blockers_layout = QVBoxLayout(blockers_box)
        self.blocker_list = StaticListWidget(parent=blockers_box)
        blockers_layout.addWidget(self.blocker_list)
        layout.addWidget(blockers_box, stretch=1)

        manual_box = OperatorPanel("Manual Review Companion", widget)
        manual_layout = QVBoxLayout(manual_box)
        self.manual_list = StaticListWidget(parent=manual_box)
        manual_layout.addWidget(self.manual_list)
        layout.addWidget(manual_box, stretch=1)
        return widget

    def _action_tab_text(self, action: DesktopActionChoice) -> str:
        normalized = action.action_id.split("__", 1)[0]
        mapping = {
            "qa_stack": "STACK",
            "repo_checker_profile": "REPO",
            "scene_check": "SCENE",
            "unused_resources": "UNUSED",
            "delivery_checklist": "DELIVERY",
        }
        return mapping.get(normalized, action.label)

    def _clear_action_tabs(self) -> None:
        self._action_tab_buttons.clear()
        while self.action_tab_layout.count():
            item = self.action_tab_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _reload_profiles(self) -> None:
        profiles = desktop_profiles(self.workspace_root)
        self.profile_list.clear()
        selected_row = 0
        for index, profile in enumerate(profiles):
            item = QListWidgetItem(f"{profile.profile_id}  {profile.label}")
            item.setToolTip(profile.summary)
            item.setData(Qt.UserRole, profile.profile_id)
            self.profile_list.addItem(item)
            if self.initial_profile_id and profile.profile_id.upper() == self.initial_profile_id:
                selected_row = index
        if self.profile_list.count():
            self.profile_list.setCurrentRow(selected_row)

    def _profile_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None = None) -> None:
        del previous
        profile_id = str(current.data(Qt.UserRole)) if current is not None else ""
        self._reload_actions(profile_id)
        self._reload_side_panels(profile_id)
        self._load_latest_snapshot(profile_id)

    def _reload_actions(self, profile_id: str) -> None:
        self.action_list.clear()
        self._clear_action_tabs()
        actions = desktop_actions_for_profile(profile_id, self.workspace_root)
        for action in actions:
            state = "available" if action.ready else "unavailable"
            item = QListWidgetItem(f"{action.label} [{state}]")
            tooltip = action.description
            if action.blocker_message:
                tooltip += f"\n\n{action.blocker_message}"
            item.setToolTip(tooltip)
            item.setData(Qt.UserRole, action.action_id)
            item.setData(Qt.UserRole + 1, action)
            self.action_list.addItem(item)

            button = ActionTabButton(action.action_id, self._action_tab_text(action), action.ready, self.action_tab_host)
            button.setToolTip(tooltip)
            button.selected.connect(self._select_action_by_id)
            self.action_tab_layout.addWidget(button)
            self._action_tab_buttons[action.action_id] = button

        self.action_tab_layout.addStretch(1)
        if self.action_list.count():
            self.action_list.setCurrentRow(0)

    def _reload_side_panels(self, profile_id: str) -> None:
        self._reload_dependency_setup_panel()

        self.surface_list.clear()
        for item in desktop_surface_items(profile_id, self.workspace_root):
            row = QListWidgetItem(f"{item.label} [{item.state}]\n{item.summary}")
            row.setToolTip(item.summary)
            self.surface_list.addItem(row)

        self.blocker_list.clear()
        for item in desktop_blocker_items(profile_id, self.workspace_root):
            text = f"{item.label} [{item.state}]"
            text += f"\n{item.blockers[0] if item.blockers else item.summary}"
            row = QListWidgetItem(text)
            row.setToolTip(item.summary)
            self.blocker_list.addItem(row)

        self.manual_list.clear()
        for item in desktop_manual_cards(profile_id, self.workspace_root):
            row = QListWidgetItem(f"{item.label} [{item.state}]\n{item.note}")
            row.setToolTip(item.summary)
            self.manual_list.addItem(row)

    def _reload_dependency_setup_panel(self, *, preserve_output: bool = False) -> None:
        try:
            status = build_dependency_onboarding_status(workspace=self.workspace_root)
        except Exception as exc:  # noqa: BLE001
            self._setup_status = {"status": "unknown", "summary": str(exc), "items": [], "actions": []}
            self._setup_actions = []
            self.setup_status_label.setText(f"unknown - Dependency setup status failed: {exc}")
            self.setup_list.clear()
            self.setup_action_selector.clear()
            self.setup_action_selector.addItem("No setup actions available", "")
            if not preserve_output:
                self.setup_output.setPlainText("Dependency setup status could not be loaded.")
            self._refresh_dependency_setup_buttons()
            return

        self._setup_status = status
        self._setup_actions = [action for action in status.get("actions", []) if isinstance(action, dict)]
        self.setup_status_label.setText(f"{status.get('status', 'unknown')} - {status.get('summary', '')}")

        self.setup_list.clear()
        for item in status.get("items", []):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "Dependency"))
            state = str(item.get("status", "unknown"))
            detail = str(item.get("detail", ""))
            row = QListWidgetItem(f"{label} [{state}]\n{detail}")
            row.setToolTip(detail)
            self.setup_list.addItem(row)

        self.setup_action_selector.blockSignals(True)
        self.setup_action_selector.clear()
        if self._setup_actions:
            for action in self._setup_actions:
                label = str(action.get("label", "Run setup"))
                action_id = str(action.get("id", "")).strip()
                self.setup_action_selector.addItem(label, action_id)
        else:
            self.setup_action_selector.addItem("No setup actions available", "")
        self.setup_action_selector.blockSignals(False)

        if self._setup_job is None and not preserve_output:
            self.setup_output.setPlainText("No dependency setup job is running.")
        self._refresh_dependency_setup_buttons()

    def _selected_setup_action(self) -> dict[str, Any] | None:
        action_id = str(self.setup_action_selector.currentData() or "").strip()
        if not action_id:
            return None
        for action in self._setup_actions:
            if str(action.get("id", "")).strip() == action_id:
                return action
        return None

    def _refresh_dependency_setup_buttons(self) -> None:
        running = self._setup_job is not None
        self.setup_run_button.setEnabled(not running and self._selected_setup_action() is not None)
        self.setup_cancel_button.setEnabled(running)

    def _confirm_dependency_setup_action(self, action: dict[str, Any]) -> dict[str, str | None] | None:
        action_id = str(action.get("id", "")).strip()
        source_required = action_id in _SETUP_SOURCE_REQUIRED
        target_required = action_id in _SETUP_TARGET_REQUIRED
        dialog = QDialog(self)
        dialog.setWindowTitle(str(action.get("label", "Dependency setup")))
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        summary = QLabel(str(action.get("confirmation_message", "")), dialog)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        effects = [str(effect) for effect in action.get("effects", []) if str(effect).strip()]
        if effects:
            effects_label = QLabel("System changes:\n" + "\n".join(f"- {effect}" for effect in effects), dialog)
            effects_label.setWordWrap(True)
            layout.addWidget(effects_label)

        anchor = str(action.get("confluence_anchor", "")).strip()
        if anchor:
            anchor_label = QLabel(f"Confluence anchor: {anchor}", dialog)
            anchor_label.setWordWrap(True)
            layout.addWidget(anchor_label)

        if not action.get("can_run_now"):
            input_hint = QLabel(
                "This setup step needs operator-selected files, installer UI, or credentials before SGFX can run it.",
                dialog,
            )
            input_hint.setWordWrap(True)
            layout.addWidget(input_hint)

        command_preview = str(action.get("command_preview", "")).strip()
        if command_preview:
            command_box = QPlainTextEdit(dialog)
            command_box.setReadOnly(True)
            command_box.setPlainText(command_preview)
            command_box.setMaximumHeight(80)
            layout.addWidget(command_box)

        form = QFormLayout()
        source_edit: QLineEdit | None = None
        target_edit: QLineEdit | None = None
        if source_required:
            source_edit = QLineEdit(str(action.get("source_path", "")), dialog)
            form.addRow("Source path", source_edit)
        if target_required:
            target_edit = QLineEdit(str(action.get("target_path", "")), dialog)
            form.addRow("Target path", target_edit)
        if source_required or target_required:
            layout.addLayout(form)

        guardrail = QLabel("Manual review remains required. Decision: not approval — evidence only.", dialog)
        guardrail.setWordWrap(True)
        layout.addWidget(guardrail)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        continue_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        continue_button.setText("Continue")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def _input_ready() -> bool:
            if source_required and source_edit is not None and not source_edit.text().strip():
                return False
            if target_required and target_edit is not None and not target_edit.text().strip():
                return False
            return True

        def _refresh_continue_button() -> None:
            continue_button.setEnabled(_input_ready())

        if source_edit is not None:
            source_edit.textChanged.connect(_refresh_continue_button)
        if target_edit is not None:
            target_edit.textChanged.connect(_refresh_continue_button)
        _refresh_continue_button()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            "source_path": source_edit.text().strip() if source_edit is not None else None,
            "target_path": target_edit.text().strip() if target_edit is not None else None,
        }

    def _run_selected_dependency_setup(self) -> None:
        if self._setup_job is not None:
            return
        action = self._selected_setup_action()
        if action is None:
            QMessageBox.information(self, "Dependency setup", "No setup action is available.")
            return
        inputs = self._confirm_dependency_setup_action(action)
        if inputs is None:
            return
        try:
            self._setup_job = start_dependency_setup_action(
                action_id=str(action.get("id", "")),
                workspace=self.workspace_root,
                operator_confirmed=True,
                target_path=inputs.get("target_path"),
                source_path=inputs.get("source_path"),
            )
        except Exception as exc:  # noqa: BLE001
            self.setup_status_label.setText(f"failed - Dependency setup did not start: {exc}")
            QMessageBox.warning(self, "Dependency setup", f"Dependency setup did not start: {exc}")
            self._refresh_dependency_setup_buttons()
            return

        self.setup_status_label.setText("incomplete - Dependency setup running.")
        self.setup_output.setPlainText("Dependency setup running.")
        self._refresh_dependency_setup_buttons()
        self._setup_poll_timer.start()
        self._poll_dependency_setup()

    def _apply_dependency_setup_progress(self, result: dict[str, Any]) -> None:
        status = str(result.get("status", "unknown"))
        phase = str(result.get("phase", "")).strip()
        summary = str(result.get("summary", "")).strip()
        state = status if result.get("completed", True) else phase or status
        self.setup_status_label.setText(f"{state} - {summary}")

        lines = [
            f"Action: {result.get('action_id', '')}",
            f"Status: {status}",
            f"Elapsed: {result.get('elapsed_label', '00:00')} / {result.get('typical_range', '')}",
            summary,
        ]
        stdout_lines = [str(line) for line in result.get("stdout_tail_lines", []) if str(line).strip()]
        if stdout_lines:
            lines.extend(["", "Output:", *stdout_lines])
        file_activity = [item for item in result.get("file_activity", []) if isinstance(item, dict)]
        if file_activity:
            lines.append("")
            lines.append("File activity:")
            lines.extend(str(item.get("summary", "")) for item in file_activity if str(item.get("summary", "")).strip())
        self.setup_output.setPlainText("\n".join(line for line in lines if line is not None).strip())

    def _poll_dependency_setup(self) -> None:
        if self._setup_job is None:
            self._setup_poll_timer.stop()
            self._refresh_dependency_setup_buttons()
            return
        try:
            result = poll_dependency_setup_action(self._setup_job)
        except Exception as exc:  # noqa: BLE001
            self._setup_poll_timer.stop()
            self._setup_job = None
            self.setup_status_label.setText(f"failed - Dependency setup polling failed: {exc}")
            self._refresh_dependency_setup_buttons()
            return
        if result is None:
            return
        self._apply_dependency_setup_progress(result)
        if result.get("completed", True):
            self._setup_poll_timer.stop()
            self._setup_job = None
            self._reload_dependency_setup_panel(preserve_output=True)
            self._refresh_dependency_setup_buttons()
            self._notify_completion(
                title="SGFX setup finished",
                message=str(result.get("summary", "Dependency setup completed.")),
                action_id=str(result.get("action_id", "dependency-setup")),
            )

    def _cancel_dependency_setup(self) -> None:
        if self._setup_job is None:
            return
        result = cancel_dependency_setup_action(self._setup_job)
        self._apply_dependency_setup_progress(result)
        self._setup_poll_timer.stop()
        self._setup_job = None
        self._reload_dependency_setup_panel(preserve_output=True)
        self._refresh_dependency_setup_buttons()

    def _select_action_by_id(self, action_id: str) -> None:
        for index in range(self.action_list.count()):
            item = self.action_list.item(index)
            if str(item.data(Qt.UserRole)) == action_id:
                self.action_list.setCurrentItem(item)
                break

    def _sync_action_tabs(self, action_id: str) -> None:
        for candidate_id, button in self._action_tab_buttons.items():
            button.blockSignals(True)
            button.setChecked(candidate_id == action_id)
            button.blockSignals(False)

    def _action_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None = None) -> None:
        del previous
        if current is None:
            return
        profile_id = self._current_profile_id()
        action_id = str(current.data(Qt.UserRole))
        self._sync_action_tabs(action_id)
        snapshot = latest_action_snapshot_for_profile(profile_id, self.workspace_root, preferred_action_id=action_id)
        if snapshot is not None:
            self._apply_snapshot(snapshot)
            return
        action: DesktopActionChoice = current.data(Qt.UserRole + 1)
        self._apply_empty_action(action)

    def _load_latest_snapshot(self, profile_id: str) -> None:
        snapshot = latest_action_snapshot_for_profile(
            profile_id,
            self.workspace_root,
            preferred_action_id=f"qa_stack__{profile_id.lower()}",
        )
        if snapshot is None:
            self._clear_snapshot()
            return
        self._sync_action_tabs(snapshot.action_id)
        self._apply_snapshot(snapshot)

    def _apply_empty_action(self, action: DesktopActionChoice) -> None:
        self._current_snapshot = None
        self._copy_map = {}
        self.run_title.setText(action.label)
        self.run_status.setText("No completed run record yet for this action.")
        self.progress_bar.setValue(0)
        detail = action.description
        if action.blocker_message:
            detail += f"\nBlocked: {action.blocker_message}"
        self.progress_detail.setText(detail)
        self.command_label.setText(action.command_preview)
        self.summary_text.setPlainText("")
        self.log_tail.setPlainText("")
        self.evidence_list.clear()
        self._refresh_buttons()

    def _clear_snapshot(self) -> None:
        self.run_title.setText("No action selected")
        self.run_status.setText("Choose a profile and action.")
        self.progress_bar.setValue(0)
        self.progress_detail.setText("")
        self.command_label.setText("")
        self.summary_text.setPlainText("")
        self.log_tail.setPlainText("")
        self.evidence_list.clear()
        self._current_snapshot = None
        self._copy_map = {}
        self._refresh_buttons()

    def _apply_snapshot(self, snapshot: DesktopActionSnapshot) -> None:
        self._current_snapshot = snapshot
        self._copy_map = {item.key: item.text for item in snapshot.copy_items if item.text.strip()}
        self.run_title.setText(snapshot.title.upper())
        self.run_status.setText(f"{snapshot.action_id} [{snapshot.status}]")
        self.progress_bar.setValue(snapshot.progress_percent)
        detail_lines = [snapshot.progress_detail] if snapshot.progress_detail else []
        if snapshot.child_run_id:
            detail_lines.append(f"Child run: {snapshot.child_run_id}")
        self.progress_detail.setText("\n".join(detail_lines).strip())
        self.command_label.setText(snapshot.current_command)
        self.summary_text.setPlainText("\n".join(snapshot.summary_lines).strip())
        self.log_tail.setPlainText(snapshot.log_tail)
        self.evidence_list.clear()
        for item in snapshot.top_paths:
            line = item.path
            if item.line is not None:
                line += f":{item.line}"
            if item.checker:
                line += f" [{item.checker}]"
            if item.message:
                line += f"\n{item.message}"
            row = QListWidgetItem(line)
            row.setData(Qt.UserRole, item)
            row.setToolTip(item.message or item.path)
            self.evidence_list.addItem(row)
        self._sync_action_tabs(snapshot.action_id)
        self._refresh_buttons()

    def _current_profile_id(self) -> str:
        item = self.profile_list.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else ""

    def _current_action_choice(self) -> DesktopActionChoice | None:
        item = self.action_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole + 1)

    def _run_selected_action(self) -> None:
        choice = self._current_action_choice()
        if choice is None:
            return
        try:
            action = get_operator_action(choice.action_id, self.workspace_root)
        except KeyError as exc:
            QMessageBox.warning(self, "Action unavailable", str(exc))
            return
        record = build_action_record(action, self.workspace_root)
        self._current_run_id = record.run_id
        self._runner = ActionRunner(action, self.workspace_root, record)
        self._runner.finished_run.connect(self._runner_finished)
        self._runner.failed_run.connect(self._runner_failed)
        self._runner.start()
        self.statusBar().showMessage(f"Running {choice.label}")
        self._poll_timer.start()
        self._apply_snapshot(desktop_action_snapshot(record.run_id, self.workspace_root))

    def _runner_finished(self, run_id: str) -> None:
        self._current_run_id = run_id
        self._poll_current_action()
        self.statusBar().showMessage(f"Completed {run_id}")
        self._notify_completion(
            title="SGFX action finished",
            message=f"Local action completed: {run_id}",
            action_id=run_id,
        )

    def _runner_failed(self, message: str) -> None:
        self._poll_current_action()
        self.statusBar().showMessage("Action failed")
        self._notify_completion(
            title="SGFX action failed",
            message=message,
            action_id=self._current_run_id or "action",
        )
        QMessageBox.warning(self, "Action failed", message)

    def _notify_completion(self, *, title: str, message: str, action_id: str) -> None:
        try:
            notify_desktop_completion(
                title=title,
                message=message,
                workspace=self.workspace_root,
                action_id=action_id,
                profile_id=self._current_profile_id(),
            )
        except Exception:
            return

    def _poll_current_action(self) -> None:
        if not self._current_run_id:
            return
        try:
            snapshot = desktop_action_snapshot(self._current_run_id, self.workspace_root)
        except Exception:
            return
        self._apply_snapshot(snapshot)
        if snapshot.status in {"completed", "blocked", "failed"}:
            self._poll_timer.stop()
            self._reload_side_panels(snapshot.profile_id)
            self._reload_actions(snapshot.profile_id)
            self._sync_action_tabs(snapshot.action_id)

    def _selected_evidence_item(self) -> DesktopEvidenceItem | None:
        item = self.evidence_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _open_selected_evidence(self) -> None:
        item = self._selected_evidence_item()
        if item is None or not open_local_path(item.path):
            QMessageBox.information(self, "Open file", "Select a valid evidence path first.")

    def _reveal_selected_evidence(self) -> None:
        item = self._selected_evidence_item()
        if item is None or not reveal_in_file_manager(item.path):
            QMessageBox.information(self, "Reveal file", "Select a valid evidence path first.")

    def _open_log(self) -> None:
        if self._current_snapshot is None or not open_local_path(self._current_snapshot.log_path):
            QMessageBox.information(self, "Open log", "No action log is available yet.")

    def _open_latest_report(self) -> None:
        if self._current_snapshot is None or not open_local_path(self._current_snapshot.latest_run_links.html_report):
            QMessageBox.information(self, "Open report", "No HTML report is available for the selected profile yet.")

    def _open_latest_evidence(self) -> None:
        if self._current_snapshot is None or not open_local_path(self._current_snapshot.latest_run_links.output_root):
            QMessageBox.information(self, "Open evidence", "No evidence bundle is available for the selected profile yet.")

    def _screenshot_review_output_root(self, profile_id: str) -> Path:
        safe_profile = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in (profile_id.strip().lower() or "profile")
        )
        return operator_ui_root(self.workspace_root) / "screenshot-review-viewer" / safe_profile

    def _build_screenshot_review_viewer_bundle(self) -> Any:
        profile_id = self._current_profile_id() or self.initial_profile_id
        if not profile_id:
            raise ValueError("Select a profile before opening the screenshot review viewer.")
        profile = get_run_profile(profile_id, self.workspace_root)
        project_root = profile.source_project_root()
        prep = build_visual_review_prep(profile.profile_id, project_root)
        state = read_bmw_screenshot_state(
            profile.profile_id,
            workspace=self.workspace_root,
            sg_project_root=project_root,
        )
        candidate_roots = tuple(
            Path(value).resolve()
            for value in (str(state.get("actuals_root", "")).strip(),)
            if value and Path(value).is_dir()
        )
        diff_roots = tuple(
            Path(value).resolve()
            for value in (str(state.get("diff_root", "")).strip(),)
            if value and Path(value).is_dir()
        )
        expected_root_value = str(state.get("expected_root", "")).strip()
        return build_screenshot_review_viewer(
            profile.profile_id,
            project_root,
            self._screenshot_review_output_root(profile.profile_id),
            expected_root=Path(expected_root_value).resolve() if expected_root_value else None,
            candidate_roots=candidate_roots,
            diff_reference_roots=diff_roots,
            priority_names=tuple(str(item) for item in prep.priority_screenshots),
        )

    def _open_screenshot_review_viewer(self) -> None:
        try:
            bundle = self._build_screenshot_review_viewer_bundle()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Screenshot review viewer", str(exc))
            return

        html_path = bundle.html_path.resolve()
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception:  # pragma: no cover - exercised only when WebEngine is unavailable
            if not open_local_path(str(html_path)):
                QMessageBox.information(self, "Screenshot review viewer", "Viewer HTML could not be opened.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Screenshot review viewer - {bundle.viewer.profile_id}")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        note = QLabel("Manual review remains required. Decision: not approval — evidence only.", dialog)
        note.setObjectName("panelHint")
        note.setWordWrap(True)
        layout.addWidget(note)

        view = QWebEngineView(dialog)
        view.setUrl(QUrl.fromLocalFile(str(html_path)))
        layout.addWidget(view, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)

        dialog.resize(1280, 840)
        self._screenshot_review_dialog = dialog
        dialog.show()
        self.statusBar().showMessage(f"Screenshot viewer generated with {bundle.viewer.item_count} item(s)")

    def _copy_text(self, key: str) -> None:
        text = self._copy_map.get(key, "").strip()
        if not text:
            QMessageBox.information(self, "Copy", "No copy text is available for the current selection.")
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied {key.replace('_', ' ')}")

    def _show_about_dialog(self) -> None:
        from sg_preflight.dashboard.main import ABOUT_CONTENT

        dialog = QDialog(self)
        dialog.setWindowTitle("About")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        logo = QLabel(dialog)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_pixmap = QPixmap(str(runtime_asset_path("logo_sgfx.png")))
        if not logo_pixmap.isNull():
            logo.setPixmap(
                logo_pixmap.scaledToWidth(240, Qt.TransformationMode.SmoothTransformation)
            )
        layout.addWidget(logo)

        heading = QLabel(str(ABOUT_CONTENT.get("heading", "About")), dialog)
        heading.setObjectName("runTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        description = QLabel(str(ABOUT_CONTENT.get("description", "")), dialog)
        description.setWordWrap(True)
        layout.addWidget(description)

        version = QLabel(str(ABOUT_CONTENT.get("version_placeholder", "")), dialog)
        version.setObjectName("panelHint")
        layout.addWidget(version)

        anchors = ABOUT_CONTENT.get("confluence_anchors", ())
        if anchors:
            anchor_text = "\n".join(f"{label} - {anchor}" for label, anchor in anchors)
            anchors_label = QLabel(f"Confluence anchors\n{anchor_text}", dialog)
            anchors_label.setWordWrap(True)
            anchors_label.setObjectName("panelHint")
            layout.addWidget(anchors_label)

        disclosure_lines = tuple(ABOUT_CONTENT.get("data_handling_disclosure", ()))
        if disclosure_lines:
            disclosure_label = QLabel("\n".join(str(line) for line in disclosure_lines), dialog)
            disclosure_label.setWordWrap(True)
            disclosure_label.setObjectName("panelHint")
            layout.addWidget(disclosure_label)

        guardrails = QLabel("\n".join(GRAFIKS_GUARDRAILS), dialog)
        guardrails.setWordWrap(True)
        guardrails.setObjectName("panelHint")
        layout.addWidget(guardrails)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(560, 520)
        dialog.exec()

    def _refresh_buttons(self) -> None:
        has_snapshot = self._current_snapshot is not None
        has_evidence = self.evidence_list.count() > 0
        self.open_file_button.setEnabled(has_evidence)
        self.reveal_button.setEnabled(has_evidence)
        self.open_log_button.setEnabled(has_snapshot and bool(self._current_snapshot.log_path))
        self.open_report_button.setEnabled(has_snapshot and bool(self._current_snapshot.latest_run_links.html_report))
        self.open_evidence_button.setEnabled(has_snapshot and bool(self._current_snapshot.latest_run_links.output_root))
        self.copy_jira_button.setEnabled("jira" in self._copy_map)
        self.copy_qa_hero_button.setEnabled("qa_hero" in self._copy_map)
        self.copy_handoff_button.setEnabled("handoff" in self._copy_map)
