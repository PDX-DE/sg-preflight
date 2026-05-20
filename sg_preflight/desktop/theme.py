from __future__ import annotations


def desktop_stylesheet() -> str:
    return """
QWidget {
  background: transparent;
  color: #e7efe9;
  font-family: "Bahnschrift", "Segoe UI", sans-serif;
  font-size: 13px;
}
QMainWindow {
  background: #091014;
}
QLabel#modeLabel,
QLabel#panelHint,
QLabel#progressInfo,
QLabel#commandLabel,
QLabel#runStatus {
  color: #89b89e;
}
QLabel#runTitle {
  color: #ffbf54;
  font-family: "Bahnschrift SemiBold", "Segoe UI", sans-serif;
  font-size: 16px;
  letter-spacing: 0.12em;
}
QProgressBar {
  min-height: 18px;
  background: #091215;
  border: 1px solid #225846;
  border-radius: 9px;
  text-align: center;
  color: #eef7f1;
  font-family: "Bahnschrift SemiBold", "Segoe UI", sans-serif;
}
QProgressBar::chunk {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #1e9f66,
    stop:0.65 #4bf09d,
    stop:1 #a8ff7d);
  border-radius: 8px;
}
QPlainTextEdit,
QListWidget {
  background: transparent;
  border: 1px solid #18362d;
  border-radius: 8px;
  selection-background-color: rgba(29, 106, 71, 180);
  selection-color: #ffffff;
  padding: 4px;
}
QPlainTextEdit {
  font-family: "Consolas", "Cascadia Mono", monospace;
  color: #dfe9e2;
}
QPlainTextEdit#summaryText,
QPlainTextEdit#logTail {
  background: rgba(5, 11, 14, 170);
}
QListWidget::item {
  background: transparent;
  color: #deebe4;
  padding: 7px 8px;
  margin: 2px 0px;
  border: 1px solid transparent;
}
QListWidget::item:selected {
  background: rgba(22, 106, 71, 165);
  color: #ffffff;
  border: 1px solid rgba(140, 255, 187, 100);
}
QListWidget::item:hover:!selected {
  background: rgba(22, 49, 55, 130);
}
QScrollBar:vertical {
  background: rgba(8, 14, 16, 180);
  width: 12px;
  margin: 2px;
}
QScrollBar::handle:vertical {
  background: rgba(133, 255, 170, 120);
  min-height: 24px;
  border-radius: 5px;
  border: 1px solid rgba(255, 191, 84, 80);
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
  background: transparent;
  border: none;
}
QScrollBar:horizontal {
  background: rgba(8, 14, 16, 180);
  height: 12px;
  margin: 2px;
}
QScrollBar::handle:horizontal {
  background: rgba(133, 255, 170, 120);
  min-width: 24px;
  border-radius: 5px;
  border: 1px solid rgba(255, 191, 84, 80);
}
QStatusBar {
  background: rgba(9, 16, 20, 235);
  color: #8bd8ab;
  border-top: 1px solid rgba(48, 132, 88, 120);
}
QSplitter::handle {
  background: rgba(25, 78, 57, 120);
  width: 3px;
}
QPushButton#presentationToggle {
  background: #10181c;
  color: #dfe9e2;
  border: 1px solid #225846;
  border-radius: 5px;
  padding: 4px 10px;
  font-family: "Bahnschrift SemiBold", "Segoe UI", sans-serif;
}
QPushButton#presentationToggle:checked {
  background: #146a47;
  color: #ffffff;
  border: 1px solid #74f6a6;
}
*[sgfxMode="clean"] {
  color: #17212b;
  font-family: "Segoe UI", sans-serif;
  font-size: 12px;
}
QLabel[sgfxMode="clean"]#modeLabel,
QLabel[sgfxMode="clean"]#panelHint,
QLabel[sgfxMode="clean"]#progressInfo,
QLabel[sgfxMode="clean"]#commandLabel,
QLabel[sgfxMode="clean"]#runStatus {
  color: #596775;
}
QLabel[sgfxMode="clean"]#runTitle {
  color: #16212c;
  font-family: "Segoe UI Semibold", "Segoe UI", sans-serif;
  font-size: 15px;
  letter-spacing: 0;
}
QPlainTextEdit[sgfxMode="clean"],
QListWidget[sgfxMode="clean"] {
  background: #ffffff;
  border: 1px solid #d6dde4;
  border-radius: 4px;
  selection-background-color: #dbeafe;
  selection-color: #17212b;
  color: #17212b;
}
QPlainTextEdit[sgfxMode="clean"]#summaryText,
QPlainTextEdit[sgfxMode="clean"]#logTail {
  background: #ffffff;
}
QListWidget[sgfxMode="clean"]::item {
  background: transparent;
  color: #17212b;
  padding: 6px 7px;
  margin: 1px 0px;
  border: 1px solid transparent;
}
QListWidget[sgfxMode="clean"]::item:selected {
  background: #dbeafe;
  color: #17212b;
  border: 1px solid #8fb7df;
}
QListWidget[sgfxMode="clean"]::item:hover:!selected {
  background: #f1f5f9;
}
QProgressBar[sgfxMode="clean"] {
  min-height: 16px;
  background: #ffffff;
  border: 1px solid #cbd5df;
  border-radius: 4px;
  text-align: center;
  color: #17212b;
}
QProgressBar[sgfxMode="clean"]::chunk {
  background: #4e7aa6;
  border-radius: 3px;
}
QStatusBar[sgfxMode="clean"] {
  background: #ffffff;
  color: #41505e;
  border-top: 1px solid #d6dde4;
}
QSplitter[sgfxMode="clean"]::handle {
  background: #d6dde4;
  width: 3px;
}
QPushButton[sgfxMode="clean"]#presentationToggle {
  background: #ffffff;
  color: #25313d;
  border: 1px solid #cbd5df;
  border-radius: 4px;
  padding: 4px 10px;
  font-family: "Segoe UI Semibold", "Segoe UI", sans-serif;
}
QPushButton[sgfxMode="clean"]#presentationToggle:checked {
  background: #dbeafe;
  color: #17212b;
  border: 1px solid #7da8d2;
}
"""
