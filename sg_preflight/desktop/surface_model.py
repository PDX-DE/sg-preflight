"""Qt list model exposing the surface registry's page/panel descriptors to QML."""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum
from typing import Any

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Property, Qt

from sg_preflight.surface_registry import SURFACE_DESCRIPTORS, SurfaceDescriptor


class SurfaceRole(IntEnum):
    SurfaceId = int(Qt.ItemDataRole.UserRole) + 1
    Title = SurfaceId + 1
    Subtitle = SurfaceId + 2
    Group = SurfaceId + 3
    RendererKind = SurfaceId + 4
    Operational = SurfaceId + 5


_ROLE_NAMES = {
    int(SurfaceRole.SurfaceId): QByteArray(b"surfaceId"),
    int(SurfaceRole.Title): QByteArray(b"title"),
    int(SurfaceRole.Subtitle): QByteArray(b"subtitle"),
    int(SurfaceRole.Group): QByteArray(b"group"),
    int(SurfaceRole.RendererKind): QByteArray(b"rendererKind"),
    int(SurfaceRole.Operational): QByteArray(b"operational"),
}


class SurfaceRegistryModel(QAbstractListModel):
    def __init__(
        self,
        descriptors: Sequence[SurfaceDescriptor] = SURFACE_DESCRIPTORS,
        parent: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self._descriptors = tuple(descriptors)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._descriptors)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._descriptors):
            return None
        descriptor = self._descriptors[index.row()]
        values = {
            int(SurfaceRole.SurfaceId): descriptor.surface_id,
            int(SurfaceRole.Title): descriptor.title,
            int(SurfaceRole.Subtitle): descriptor.subtitle,
            int(SurfaceRole.Group): descriptor.navigation_group,
            int(SurfaceRole.RendererKind): descriptor.renderer_kind,
            int(SurfaceRole.Operational): descriptor.operational,
        }
        return values.get(role)

    def roleNames(self) -> dict[int, QByteArray]:
        return dict(_ROLE_NAMES)

    @Property(int, constant=True)
    def count(self) -> int:
        return len(self._descriptors)

    def descriptor(self, row: int) -> SurfaceDescriptor:
        return self._descriptors[row]
