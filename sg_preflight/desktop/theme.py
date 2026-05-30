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
QLabel#grafiksWipNotice {
  color: #ffd57a;
  background: rgba(50, 32, 8, 200);
  border: 1px solid rgba(255, 191, 84, 130);
  border-radius: 5px;
  padding: 8px 12px;
  font-family: "Bahnschrift SemiBold", "Segoe UI", sans-serif;
  font-size: 12px;
  letter-spacing: 0.04em;
  margin: 2px 0;
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
  padding: 4px 10px;
}
QSplitter::handle {
  background: rgba(25, 78, 57, 120);
  width: 4px;
}
QGroupBox {
  margin-top: 14px;
  padding: 8px;
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
  color: #d4d4d4;
  font-family: "Segoe UI", "Cascadia Code", sans-serif;
  font-size: 12px;
}
QMainWindow[sgfxMode="clean"] {
  background: #1e1e1e;
}
QLabel[sgfxMode="clean"]#modeLabel,
QLabel[sgfxMode="clean"]#panelHint,
QLabel[sgfxMode="clean"]#progressInfo,
QLabel[sgfxMode="clean"]#commandLabel,
QLabel[sgfxMode="clean"]#runStatus {
  color: #9da3a8;
}
QLabel[sgfxMode="clean"]#runTitle {
  color: #ececec;
  font-family: "Segoe UI Semibold", "Segoe UI", sans-serif;
  font-size: 15px;
  letter-spacing: 0;
}
QLabel[sgfxMode="clean"]#grafiksWipNotice {
  color: #e8c07d;
  background: rgba(58, 47, 24, 220);
  border: 1px solid rgba(107, 80, 36, 200);
}
QPlainTextEdit[sgfxMode="clean"],
QListWidget[sgfxMode="clean"] {
  background: #252526;
  border: 1px solid #3c3c3c;
  border-radius: 5px;
  selection-background-color: #264f44;
  selection-color: #ececec;
  color: #d4d4d4;
  padding: 5px;
}
QPlainTextEdit[sgfxMode="clean"]#summaryText,
QPlainTextEdit[sgfxMode="clean"]#logTail {
  background: #1e1e1e;
}
QListWidget[sgfxMode="clean"]::item {
  background: transparent;
  color: #d4d4d4;
  padding: 7px 8px;
  margin: 2px 0px;
  border: 1px solid transparent;
}
QListWidget[sgfxMode="clean"]::item:selected {
  background: #264f44;
  color: #ececec;
  border: 1px solid #4ec9b0;
}
QListWidget[sgfxMode="clean"]::item:hover:!selected {
  background: #2b2b2b;
}
QProgressBar[sgfxMode="clean"] {
  min-height: 18px;
  background: #252526;
  border: 1px solid #3c3c3c;
  border-radius: 5px;
  text-align: center;
  color: #d4d4d4;
}
QProgressBar[sgfxMode="clean"]::chunk {
  background: #4ec9b0;
  border-radius: 4px;
}
QStatusBar[sgfxMode="clean"] {
  background: #252526;
  color: #9da3a8;
  border-top: 1px solid #3c3c3c;
}
QSplitter[sgfxMode="clean"]::handle {
  background: #3c3c3c;
  width: 3px;
}
QPushButton[sgfxMode="clean"]#presentationToggle {
  background: #2b2b2b;
  color: #d4d4d4;
  border: 1px solid #3c3c3c;
  border-radius: 5px;
  padding: 5px 12px;
  font-family: "Segoe UI Semibold", "Segoe UI", sans-serif;
}
QPushButton[sgfxMode="clean"]#presentationToggle:checked {
  background: #264f44;
  color: #ececec;
  border: 1px solid #4ec9b0;
}
"""
