from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from sg_preflight.qa_actions import ActionRecord, OperatorAction, execute_operator_action


class ActionRunner(QThread):
    finished_run = Signal(str)
    failed_run = Signal(str)

    def __init__(self, action: OperatorAction, workspace_root: Path, record: ActionRecord) -> None:
        super().__init__()
        self._action = action
        self._workspace_root = workspace_root
        self._record = record

    def run(self) -> None:
        try:
            record = execute_operator_action(self._action, self._workspace_root, record=self._record)
        except Exception as exc:
            self.failed_run.emit(str(exc))
            return
        self.finished_run.emit(record.run_id)
