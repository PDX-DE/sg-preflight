from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
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

from sg_preflight.desktop.evidence_model import (
    DesktopActionChoice,
    DesktopActionSnapshot,
    DesktopEvidenceItem,
    desktop_action_snapshot,
    desktop_actions_for_profile,
    desktop_blocker_items,
    desktop_manual_cards,
    desktop_profiles,
    latest_action_snapshot_for_profile,
)
from sg_preflight.desktop.file_ops import open_local_path, reveal_in_file_manager
from sg_preflight.desktop.workers import ActionRunner
from sg_preflight.qa_actions import build_action_record, get_operator_action
from sg_preflight.services import workspace_root


class DesktopMainWindow(QMainWindow):
    def __init__(self, *, workspace: Path | None = None, initial_profile_id: str = "") -> None:
        super().__init__()
        self.workspace_root = workspace_root(workspace)
        self.initial_profile_id = initial_profile_id.strip().upper()
        self._runner: ActionRunner | None = None
        self._current_run_id = ""
        self._current_snapshot: DesktopActionSnapshot | None = None
        self._copy_map: dict[str, str] = {}

        self.setWindowTitle("SG Preflight - QA Operator Shell")
        self.resize(1540, 920)
        self._build_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(800)
        self._poll_timer.timeout.connect(self._poll_current_action)
        self._reload_profiles()

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        title = QLabel("SG Preflight")
        title.setProperty("role", "title")
        subtitle = QLabel("QA Operator Shell")
        subtitle.setProperty("role", "subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

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

        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self._run_selected_action)
        bottom_layout.addWidget(self.run_button)

        self.open_file_button = QPushButton("Open File")
        self.open_file_button.clicked.connect(self._open_selected_evidence)
        bottom_layout.addWidget(self.open_file_button)

        self.reveal_button = QPushButton("Reveal")
        self.reveal_button.clicked.connect(self._reveal_selected_evidence)
        bottom_layout.addWidget(self.reveal_button)

        self.open_log_button = QPushButton("Open Raw Log")
        self.open_log_button.clicked.connect(self._open_log)
        bottom_layout.addWidget(self.open_log_button)

        self.open_report_button = QPushButton("Open Latest Report")
        self.open_report_button.clicked.connect(self._open_latest_report)
        bottom_layout.addWidget(self.open_report_button)

        self.open_evidence_button = QPushButton("Open Latest Evidence")
        self.open_evidence_button.clicked.connect(self._open_latest_evidence)
        bottom_layout.addWidget(self.open_evidence_button)

        self.copy_jira_button = QPushButton("Copy Jira Note")
        self.copy_jira_button.clicked.connect(lambda: self._copy_text("jira"))
        bottom_layout.addWidget(self.copy_jira_button)

        self.copy_qa_hero_button = QPushButton("Copy QA Hero Note")
        self.copy_qa_hero_button.clicked.connect(lambda: self._copy_text("qa_hero"))
        bottom_layout.addWidget(self.copy_qa_hero_button)

        self.copy_handoff_button = QPushButton("Copy Handoff")
        self.copy_handoff_button.clicked.connect(lambda: self._copy_text("handoff"))
        bottom_layout.addWidget(self.copy_handoff_button)

        layout.addWidget(bottom)
        self.setCentralWidget(central)

        status = QStatusBar(self)
        status.showMessage("Desktop Operator Shell v0")
        self.setStatusBar(status)

    def _build_left_column(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        profiles_box = QGroupBox("Profiles", widget)
        profiles_layout = QVBoxLayout(profiles_box)
        self.profile_list = QListWidget(profiles_box)
        self.profile_list.currentItemChanged.connect(self._profile_changed)
        profiles_layout.addWidget(self.profile_list)
        layout.addWidget(profiles_box, stretch=1)

        actions_box = QGroupBox("Actions", widget)
        actions_layout = QVBoxLayout(actions_box)
        self.action_list = QListWidget(actions_box)
        self.action_list.currentItemChanged.connect(self._action_changed)
        actions_layout.addWidget(self.action_list)
        layout.addWidget(actions_box, stretch=2)
        return widget

    def _build_center_column(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        run_box = QGroupBox("Active Run / Result", widget)
        run_layout = QVBoxLayout(run_box)

        self.run_title = QLabel("No action selected")
        self.run_title.setProperty("role", "subtitle")
        run_layout.addWidget(self.run_title)

        self.run_status = QLabel("Choose a profile and action.")
        run_layout.addWidget(self.run_status)

        self.progress_bar = QProgressBar(run_box)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        run_layout.addWidget(self.progress_bar)

        self.progress_detail = QLabel("")
        self.progress_detail.setWordWrap(True)
        run_layout.addWidget(self.progress_detail)

        self.command_label = QLabel("")
        self.command_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.command_label.setWordWrap(True)
        run_layout.addWidget(self.command_label)

        summary_box = QGroupBox("Summary", run_box)
        summary_layout = QVBoxLayout(summary_box)
        self.summary_text = QPlainTextEdit(summary_box)
        self.summary_text.setReadOnly(True)
        summary_layout.addWidget(self.summary_text)
        run_layout.addWidget(summary_box, stretch=2)

        log_box = QGroupBox("Log Tail", run_box)
        log_layout = QVBoxLayout(log_box)
        self.log_tail = QPlainTextEdit(log_box)
        self.log_tail.setReadOnly(True)
        log_layout.addWidget(self.log_tail)
        run_layout.addWidget(log_box, stretch=2)

        layout.addWidget(run_box, stretch=1)
        return widget

    def _build_right_column(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        evidence_box = QGroupBox("Open First", widget)
        evidence_layout = QVBoxLayout(evidence_box)
        self.evidence_list = QListWidget(evidence_box)
        evidence_layout.addWidget(self.evidence_list)
        layout.addWidget(evidence_box, stretch=2)

        blockers_box = QGroupBox("Blockers", widget)
        blockers_layout = QVBoxLayout(blockers_box)
        self.blocker_list = QListWidget(blockers_box)
        blockers_layout.addWidget(self.blocker_list)
        layout.addWidget(blockers_box, stretch=1)

        manual_box = QGroupBox("Manual Review Companion", widget)
        manual_layout = QVBoxLayout(manual_box)
        self.manual_list = QListWidget(manual_box)
        manual_layout.addWidget(self.manual_list)
        layout.addWidget(manual_box, stretch=1)
        return widget

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
        for action in desktop_actions_for_profile(profile_id, self.workspace_root):
            state = "ready" if action.ready else "blocked"
            item = QListWidgetItem(f"{action.label} [{state}]")
            tooltip = action.description
            if action.blocker_message:
                tooltip += f"\n\n{action.blocker_message}"
            item.setToolTip(tooltip)
            item.setData(Qt.UserRole, action.action_id)
            item.setData(Qt.UserRole + 1, action)
            self.action_list.addItem(item)
        if self.action_list.count():
            self.action_list.setCurrentRow(0)

    def _reload_side_panels(self, profile_id: str) -> None:
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

    def _action_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None = None) -> None:
        del previous
        if current is None:
            return
        profile_id = self._current_profile_id()
        action_id = str(current.data(Qt.UserRole))
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
        self.run_title.setText(snapshot.title)
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
            self.evidence_list.addItem(row)
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

    def _runner_failed(self, message: str) -> None:
        self._poll_current_action()
        self.statusBar().showMessage("Action failed")
        QMessageBox.warning(self, "Action failed", message)

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

    def _copy_text(self, key: str) -> None:
        text = self._copy_map.get(key, "").strip()
        if not text:
            QMessageBox.information(self, "Copy", "No copy-ready text is available for the current selection.")
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"Copied {key.replace('_', ' ')}")

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
