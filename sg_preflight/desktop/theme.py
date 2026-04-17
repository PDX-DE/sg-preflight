from __future__ import annotations


def desktop_stylesheet() -> str:
    return """
QWidget {
  background: #101416;
  color: #dde5df;
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 13px;
}
QMainWindow {
  background: #0a0f11;
}
QLabel[role="title"] {
  color: #ffbf54;
  font-size: 22px;
  font-weight: 700;
}
QLabel[role="subtitle"] {
  color: #7fc9a5;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
QGroupBox {
  border: 1px solid #1f3a34;
  border-radius: 10px;
  margin-top: 14px;
  padding: 14px 10px 10px 10px;
  background: #11181b;
}
QGroupBox::title {
  subcontrol-origin: margin;
  left: 10px;
  padding: 0 6px;
  color: #ffbf54;
  background: #11181b;
}
QListWidget, QPlainTextEdit {
  background: #0d1417;
  border: 1px solid #203630;
  border-radius: 8px;
  selection-background-color: #18392f;
  selection-color: #f2f6f3;
}
QPlainTextEdit {
  font-family: "Consolas", "Cascadia Mono", monospace;
}
QPushButton {
  background: #163026;
  border: 1px solid #2a5d49;
  border-radius: 8px;
  padding: 8px 12px;
  color: #eaf3ee;
  font-weight: 600;
}
QPushButton:hover {
  background: #1a3a2d;
}
QPushButton:pressed {
  background: #214536;
}
QPushButton:disabled {
  color: #7b8780;
  background: #141818;
  border-color: #232928;
}
QProgressBar {
  background: #0d1417;
  border: 1px solid #203630;
  border-radius: 8px;
  text-align: center;
  color: #eaf3ee;
}
QProgressBar::chunk {
  background: #43b37a;
  border-radius: 7px;
}
QStatusBar {
  background: #0d1214;
  color: #89c7a9;
}
QSplitter::handle {
  background: #163026;
}
"""

