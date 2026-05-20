from __future__ import annotations

import math
from pathlib import Path
from random import Random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGroupBox, QPushButton, QWidget, QListWidget


AMBER = QColor("#ffbf54")
AMBER_SOFT = QColor("#f9d98d")
GREEN = QColor("#74f6a6")
GREEN_SOFT = QColor("#49c889")
GREEN_DARK = QColor("#0d3f31")
SURFACE = QColor("#11161a")
SURFACE_DEEP = QColor("#0b1114")
INK = QColor("#e7efe9")
MUTED = QColor("#87ad98")
PANEL_LINE = QColor("#225846")


def _widget_mode(widget: QWidget) -> str:
    value = str(widget.property("sgfxMode") or "clean").strip().casefold()
    return value if value in {"clean", "grafiks"} else "clean"


def _is_clean(widget: QWidget) -> bool:
    return _widget_mode(widget) == "clean"


def _with_alpha(color: QColor, alpha: int) -> QColor:
    tinted = QColor(color)
    tinted.setAlpha(max(0, min(alpha, 255)))
    return tinted


class OperatorChrome(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        if _is_clean(self):
            painter.fillRect(rect, QColor("#f5f7f8"))
            painter.setPen(QPen(QColor("#d7dde2"), 1))
            grid_step = 64
            for x in range(0, rect.width(), grid_step):
                painter.drawLine(x, 0, x, rect.height())
            for y in range(0, rect.height(), grid_step):
                painter.drawLine(0, y, rect.width(), y)
            painter.fillRect(QRectF(0.0, 0.0, float(rect.width()), 54.0), QColor("#ffffff"))
            painter.setPen(QPen(QColor("#c7d0d8"), 1))
            painter.drawLine(0, 54, rect.width(), 54)
            return

        background = QLinearGradient(0.0, 0.0, 0.0, float(rect.height()))
        background.setColorAt(0.0, QColor("#0f1315"))
        background.setColorAt(0.35, QColor("#0b1114"))
        background.setColorAt(1.0, QColor("#081013"))
        painter.fillRect(rect, background)

        painter.setPen(QPen(_with_alpha(QColor("#204234"), 50), 1))
        grid_step = 46
        for x in range(0, rect.width(), grid_step):
            painter.drawLine(x, 0, x, rect.height())
        for y in range(0, rect.height(), grid_step):
            painter.drawLine(0, y, rect.width(), y)

        self._draw_bar(
            painter,
            QRectF(0.0, 0.0, float(rect.width()), 96.0),
            invert=False,
        )
        self._draw_bar(
            painter,
            QRectF(0.0, float(rect.height() - 112), float(rect.width()), 112.0),
            invert=True,
        )

    def _draw_bar(self, painter: QPainter, rect: QRectF, *, invert: bool) -> None:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if invert:
            gradient.setColorAt(0.0, _with_alpha(QColor("#09291f"), 0))
            gradient.setColorAt(0.35, _with_alpha(QColor("#1d704f"), 40))
            gradient.setColorAt(1.0, _with_alpha(QColor("#b9ff4d"), 18))
        else:
            gradient.setColorAt(0.0, _with_alpha(QColor("#b9ff4d"), 18))
            gradient.setColorAt(0.7, _with_alpha(QColor("#1d704f"), 38))
            gradient.setColorAt(1.0, _with_alpha(QColor("#09291f"), 0))
        painter.fillRect(rect, gradient)

        center_y = rect.bottom() - 2 if invert else rect.bottom() - 4
        painter.fillRect(QRectF(rect.left(), center_y, rect.width(), 1.5), QColor("#4ad67e"))
        painter.fillRect(QRectF(rect.left(), center_y + 2.0, rect.width(), 2.5), _with_alpha(QColor("#d7ff8f"), 38))

        painter.setPen(QPen(_with_alpha(QColor("#9dff74"), 24), 1))
        step = 6
        if invert:
            positions = range(int(rect.top()), int(rect.bottom()), step)
        else:
            positions = range(int(rect.top()), int(rect.bottom()), step)
        for y in positions:
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)


class HeaderBanner(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str,
        parent: QWidget | None = None,
        *,
        logo_path: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.subtitle = subtitle
        self.logo_path = Path(logo_path) if logo_path else None
        self.logo_pixmap = QPixmap(str(self.logo_path)) if self.logo_path and self.logo_path.is_file() else QPixmap()
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.setMinimumHeight(92)

    def _tick(self) -> None:
        self._phase = (self._phase + 0.11) % (math.pi * 2.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        if _is_clean(self):
            painter.fillRect(rect, QColor("#ffffff"))
            title_font = QFont("Segoe UI Semibold", 17)
            subtitle_font = QFont("Segoe UI", 9)
            painter.setPen(QColor("#17212b"))
            painter.setFont(title_font)
            painter.drawText(QRectF(0.0, 8.0, rect.width(), 32.0), Qt.AlignLeft | Qt.AlignVCenter, self.title)
            painter.setPen(QColor("#66717c"))
            painter.setFont(subtitle_font)
            painter.drawText(QRectF(0.0, 42.0, rect.width(), 18.0), Qt.AlignLeft | Qt.AlignVCenter, self.subtitle)
            painter.setPen(QPen(QColor("#d5dce3"), 1))
            painter.drawLine(0, int(rect.bottom() - 8), int(rect.width()), int(rect.bottom() - 8))
            return

        painter.setPen(Qt.NoPen)
        halo = QLinearGradient(rect.topLeft(), rect.bottomRight())
        halo.setColorAt(0.0, _with_alpha(QColor("#0f3829"), 140))
        halo.setColorAt(0.55, _with_alpha(QColor("#0f3829"), 10))
        halo.setColorAt(1.0, _with_alpha(QColor("#000000"), 0))
        painter.fillRect(rect.adjusted(0, 0, -rect.width() * 0.35, 0), halo)

        title_font = QFont("Bahnschrift SemiBold", 20)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        subtitle_font = QFont("Bahnschrift SemiBold", 9)
        subtitle_font.setCapitalization(QFont.AllUppercase)
        subtitle_font.setLetterSpacing(QFont.AbsoluteSpacing, 2.1)

        painter.setPen(AMBER)
        painter.setFont(title_font)
        painter.drawText(QRectF(0.0, 10.0, rect.width(), 34.0), Qt.AlignLeft | Qt.AlignVCenter, self.title)

        painter.setPen(_with_alpha(GREEN, 210))
        painter.setFont(subtitle_font)
        painter.drawText(QRectF(0.0, 46.0, rect.width(), 18.0), Qt.AlignLeft | Qt.AlignVCenter, self.subtitle)

        pulse = 0.45 + ((math.sin(self._phase) + 1.0) * 0.25)
        square_x = 205.0
        square_y = 17.0
        square_w = 18.0
        square_h = 18.0
        painter.setBrush(_with_alpha(AMBER, int(220 * pulse)))
        painter.setPen(QPen(_with_alpha(INK, 40), 1))
        painter.drawRoundedRect(QRectF(square_x, square_y, square_w, square_h), 3.0, 3.0)

        painter.setPen(QPen(_with_alpha(GREEN, 120), 1.3))
        painter.drawLine(int(square_x + square_w + 14), 26, int(rect.width()), 26)
        painter.setPen(QPen(_with_alpha(GREEN_SOFT, 70), 1))
        painter.drawLine(int(square_x + square_w + 14), 56, int(rect.width() * 0.78), 56)

        if not self.logo_pixmap.isNull():
            logo_rect = QRectF(rect.width() - 78.0, 12.0, 62.0, 62.0)
            painter.drawPixmap(logo_rect.toRect(), self.logo_pixmap)


class OperatorPanel(QGroupBox):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setContentsMargins(16, 34, 16, 16)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = QRectF(self.rect()).adjusted(1.0, 12.0, -1.0, -1.0)
        if _is_clean(self):
            painter.fillRect(rect, QColor("#ffffff"))
            painter.setPen(QPen(QColor("#d6dde4"), 1))
            painter.drawRect(rect)
            title_font = QFont("Segoe UI Semibold", 9)
            painter.setFont(title_font)
            painter.setPen(QColor("#26323d"))
            painter.drawText(QRectF(rect.left() + 12.0, 0.0, rect.width() - 24.0, 26.0), Qt.AlignLeft | Qt.AlignVCenter, self.title())
            return

        painter.fillRect(rect, _with_alpha(SURFACE, 230))
        painter.fillRect(rect.adjusted(8.0, 8.0, -8.0, -8.0), _with_alpha(SURFACE_DEEP, 245))

        painter.setPen(QPen(_with_alpha(PANEL_LINE, 180), 1))
        painter.drawRect(rect)
        painter.setPen(QPen(_with_alpha(GREEN_DARK, 180), 1))
        painter.drawRect(rect.adjusted(6.0, 6.0, -6.0, -6.0))

        painter.setPen(QPen(_with_alpha(GREEN, 120), 2))
        painter.drawLine(int(rect.left() + 8), int(rect.top() + 18), int(rect.left() + 8), int(rect.bottom() - 10))
        painter.setPen(QPen(_with_alpha(GREEN, 90), 1))
        painter.drawLine(int(rect.left() + 14), int(rect.top() + 14), int(rect.right() - 10), int(rect.top() + 14))

        title_font = QFont("Bahnschrift SemiBold", 10)
        title_font.setCapitalization(QFont.AllUppercase)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.7)
        painter.setFont(title_font)
        painter.setPen(AMBER)
        painter.drawText(QRectF(rect.left() + 14.0, 0.0, rect.width() - 28.0, 26.0), Qt.AlignLeft | Qt.AlignVCenter, self.title())

        painter.setPen(QPen(_with_alpha(GREEN, 100), 1))
        painter.drawLine(int(rect.left() + 128), 13, int(rect.right() - 14), 13)


class ActionTabButton(QPushButton):
    selected = Signal(str)

    def __init__(self, action_id: str, label: str, ready: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action_id = action_id
        self._label = label
        self._ready = ready
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setMinimumWidth(138)
        self.clicked.connect(self._emit_selected)

    def _emit_selected(self) -> None:
        self.selected.emit(self.action_id)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        if _is_clean(self):
            active = self.isChecked()
            hovered = self.underMouse()
            fill = QColor("#e8f0f8") if active else QColor("#ffffff")
            if hovered and not active:
                fill = QColor("#f0f4f7")
            border = QColor("#4e7aa6") if active else QColor("#cfd8e1")
            painter.setPen(QPen(border, 1.1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 5.0, 5.0)
            font = QFont("Segoe UI Semibold", 9)
            painter.setFont(font)
            painter.setPen(QColor("#15212b") if self._ready else QColor("#7c8792"))
            painter.drawText(rect.adjusted(10.0, 0.0, -10.0, 0.0), Qt.AlignCenter, self._label)
            return

        active = self.isChecked()
        hovered = self.underMouse()
        border = _with_alpha(GREEN if active else PANEL_LINE, 220 if active else 170)
        fill_top = QColor("#146a47") if active else QColor("#132026")
        fill_bottom = QColor("#0c3526") if active else QColor("#0d1318")
        if hovered and not active:
            fill_top = QColor("#193137")
            fill_bottom = QColor("#10181c")

        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, fill_top)
        gradient.setColorAt(1.0, fill_bottom)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 8.0, 8.0)

        indicator_rect = QRectF(rect.left() + 8.0, rect.center().y() - 3.0, 12.0, 6.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_with_alpha(AMBER if active else QColor("#51615a"), 230 if self._ready else 130))
        painter.drawRoundedRect(indicator_rect, 3.0, 3.0)

        font = QFont("Bahnschrift SemiBold", 9)
        font.setCapitalization(QFont.AllUppercase)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        painter.setFont(font)
        painter.setPen(INK if self._ready else _with_alpha(MUTED, 180))
        painter.drawText(rect.adjusted(28.0, 0.0, -12.0, 0.0), Qt.AlignLeft | Qt.AlignVCenter, self._label)


class GuideButton(QPushButton):
    def __init__(self, guide_code: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._guide_code = guide_code
        self._label = label
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setMinimumWidth(124)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        enabled = self.isEnabled()
        hovered = self.underMouse()
        pressed = self.isDown()
        if _is_clean(self):
            fill = QColor("#ffffff") if enabled else QColor("#f0f2f4")
            if hovered and enabled:
                fill = QColor("#eef3f7")
            if pressed and enabled:
                fill = QColor("#e3ebf2")
            painter.setPen(QPen(QColor("#cbd5df") if enabled else QColor("#dde2e7"), 1.0))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 5.0, 5.0)
            font = QFont("Segoe UI Semibold", 9)
            painter.setFont(font)
            painter.setPen(QColor("#25313d") if enabled else QColor("#8e99a3"))
            painter.drawText(rect.adjusted(10.0, 0.0, -10.0, 0.0), Qt.AlignCenter, f"{self._guide_code}  {self._label}")
            return

        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor("#1b4f36") if enabled else QColor("#131719"))
        gradient.setColorAt(1.0, QColor("#103423") if enabled else QColor("#101416"))
        if hovered and enabled:
            gradient.setColorAt(0.0, QColor("#236443"))
            gradient.setColorAt(1.0, QColor("#15442e"))
        if pressed and enabled:
            gradient.setColorAt(0.0, QColor("#18462f"))
            gradient.setColorAt(1.0, QColor("#102d1f"))

        painter.setPen(QPen(_with_alpha(GREEN, 180 if enabled else 60), 1.1))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 7.0, 7.0)

        badge_rect = QRectF(rect.left() + 8.0, rect.center().y() - 11.0, 26.0, 22.0)
        painter.setBrush(_with_alpha(QColor("#0b1013"), 220))
        painter.setPen(QPen(_with_alpha(AMBER, 220 if enabled else 90), 1))
        painter.drawRoundedRect(badge_rect, 4.0, 4.0)

        badge_font = QFont("Bahnschrift SemiBold", 9)
        badge_font.setCapitalization(QFont.AllUppercase)
        badge_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        painter.setFont(badge_font)
        painter.setPen(AMBER if enabled else _with_alpha(AMBER, 100))
        painter.drawText(badge_rect, Qt.AlignCenter, self._guide_code)

        label_font = QFont("Bahnschrift SemiBold", 9)
        painter.setFont(label_font)
        painter.setPen(INK if enabled else _with_alpha(MUTED, 150))
        painter.drawText(rect.adjusted(44.0, 0.0, -12.0, 0.0), Qt.AlignCenter, self._label)


class StaticListWidget(QListWidget):
    def __init__(self, *, flash: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._flash = flash
        self._seed = 17
        if flash:
            self._timer = QTimer(self)
            self._timer.setInterval(140)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
        else:
            self._timer = None

    def _tick(self) -> None:
        self._seed = (self._seed + 7) % 997
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = QRectF(self.viewport().rect())
        if _is_clean(self):
            painter.fillRect(rect, QColor("#ffffff"))
            super().paintEvent(event)
            return

        bg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        bg.setColorAt(0.0, QColor("#0d1417"))
        bg.setColorAt(1.0, QColor("#090f12"))
        painter.fillRect(rect, bg)

        painter.setPen(QPen(_with_alpha(QColor("#1d6b4b"), 26), 1))
        for y in range(0, int(rect.height()), 5):
            painter.drawLine(0, y, int(rect.width()), y)

        if self._flash:
            rng = Random(self._seed)
            painter.setPen(Qt.NoPen)
            for _ in range(42):
                alpha = rng.randint(6, 24)
                width = rng.randint(16, 78)
                x = rng.randint(0, max(0, int(rect.width()) - width))
                y = rng.randint(0, max(0, int(rect.height()) - 2))
                painter.setBrush(_with_alpha(QColor("#d5fff1"), alpha))
                painter.drawRect(x, y, width, 1)

            flare = 18 + int(abs(math.sin(self._seed / 13.0)) * 28)
            painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 10.0), _with_alpha(QColor("#f6ffcb"), flare))

        super().paintEvent(event)
