from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from sg_preflight.dashboard.main import _find_open_dashboard_port
from sg_preflight.subprocess_utils import hidden_subprocess_kwargs


class CleanDashboardWindow(QMainWindow):
    switch_requested = Signal(str)

    def __init__(self, *, workspace: Path, initial_profile_id: str = "") -> None:
        super().__init__()
        self.workspace = workspace
        self.initial_profile_id = initial_profile_id.strip().upper()
        self.port = _find_open_dashboard_port()
        self._server: subprocess.Popen[bytes] | None = None
        self._poll_count = 0
        self._ready = False

        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError as exc:
            raise RuntimeError("Clean mode requires the PySide6 QtWebEngineWidgets runtime.") from exc

        self.setWindowTitle("SGFX: Project Quality-Hero - Clean Operator Console")
        self.resize(1440, 900)

        central = QWidget(self)
        central.setProperty("sgfxMode", "clean")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        bar = QWidget(central)
        bar.setProperty("sgfxMode", "clean")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(6)

        self.clean_button = QPushButton("Clean", bar)
        self.grafiks_button = QPushButton("Grafiks", bar)
        for button in (self.clean_button, self.grafiks_button):
            button.setObjectName("presentationToggle")
            button.setProperty("sgfxMode", "clean")
            button.setCheckable(True)
            button.setMinimumHeight(30)
            button.setMinimumWidth(96)
        self.clean_button.setChecked(True)
        self.grafiks_button.clicked.connect(lambda: self.switch_requested.emit("grafiks"))
        bar_layout.addWidget(self.clean_button)
        bar_layout.addWidget(self.grafiks_button)

        self.status_label = QLabel("Starting Clean dashboard...", bar)
        self.status_label.setObjectName("panelHint")
        self.status_label.setProperty("sgfxMode", "clean")
        bar_layout.addWidget(self.status_label, stretch=1)
        layout.addWidget(bar)

        self.web_view = QWebEngineView(central)
        self.web_view.setProperty("sgfxMode", "clean")
        layout.addWidget(self.web_view, stretch=1)
        self.setCentralWidget(central)

        self._start_server()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(350)
        self._poll_timer.timeout.connect(self._poll_server)
        self._poll_timer.start()

    def _server_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            command = [sys.executable, "dashboard", "run"]
        else:
            command = [sys.executable, "-B", "-m", "sg_preflight", "dashboard", "run"]
        command.extend(
            [
                "--workspace",
                str(self.workspace),
                "--ui-mode",
                "clean",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--no-native",
            ]
        )
        if self.initial_profile_id:
            command.extend(["--profile", self.initial_profile_id])
        return command

    def _start_server(self) -> None:
        env = os.environ.copy()
        env["SGFX_PREFLIGHT_EMBEDDED_CLEAN"] = "1"
        self._server = subprocess.Popen(
            self._server_command(),
            cwd=self.workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            **hidden_subprocess_kwargs(),
        )

    def _poll_server(self) -> None:
        if self._ready:
            return
        self._poll_count += 1
        if self._server is not None and self._server.poll() is not None:
            self._poll_timer.stop()
            self.status_label.setText(f"Clean dashboard exited early with code {self._server.returncode}.")
            return
        url = f"http://127.0.0.1:{self.port}/"
        try:
            with urllib.request.urlopen(url, timeout=0.25) as response:
                if response.status != 200:
                    raise urllib.error.URLError(f"HTTP {response.status}")
        except Exception:
            if self._poll_count > 90:
                self._poll_timer.stop()
                self.status_label.setText("Clean dashboard did not become ready.")
            return
        self._ready = True
        self._poll_timer.stop()
        self.status_label.setText("Clean dashboard")
        self.web_view.setUrl(QUrl(url))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._server is not None and self._server.poll() is None:
            self._server.terminate()
            try:
                self._server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._server.kill()
        super().closeEvent(event)
