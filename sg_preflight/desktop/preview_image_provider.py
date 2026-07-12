from __future__ import annotations

from pathlib import Path
import re
import threading

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


class PreviewImageProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._lock = threading.RLock()
        self._frames: dict[str, tuple[Path, ...]] = {}

    @property
    def token_count(self) -> int:
        with self._lock:
            return len(self._frames)

    def register(self, token: str, frames: tuple[Path, ...]) -> bool:
        if not _TOKEN_PATTERN.fullmatch(token) or not frames:
            return False
        resolved = tuple(frame.resolve() for frame in frames)
        with self._lock:
            self._frames.clear()
            self._frames[token] = resolved
        return True

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()

    def requestImage(self, image_id: str, size: QSize, requested_size: QSize) -> QImage:
        del requested_size
        parts = str(image_id).split("/")
        if len(parts) != 2 or not _TOKEN_PATTERN.fullmatch(parts[0]):
            return QImage()
        try:
            index = int(parts[1])
        except ValueError:
            return QImage()
        with self._lock:
            frames = self._frames.get(parts[0], ())
            frame = frames[index] if 0 <= index < len(frames) else None
        if frame is None:
            return QImage()
        image = QImage(str(frame))
        if image.isNull():
            return QImage()
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image
