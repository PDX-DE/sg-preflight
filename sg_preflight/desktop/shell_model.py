"""Qt list model exposing the desktop shell's navigation routes and hub tiles to QML."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Property, Qt

from sg_preflight.shell_registry import (
    HOME_HUB_TILES,
    HOME_ROUTE_ID,
    HOME_SUBTITLE,
    HOME_TITLE,
    NAVIGATION_GROUP_ORDER,
    SHORTCUT_ACTIONS,
)
from sg_preflight.surface_registry import SURFACE_DESCRIPTORS


QT_QUICK_SHORTCUT_ACTIONS = tuple(
    (key, "Close the topmost overlay or return Home" if key == "Esc" else label)
    for key, label in SHORTCUT_ACTIONS
)


class ShellRole(IntEnum):
    RouteId = int(Qt.ItemDataRole.UserRole) + 1
    Title = RouteId + 1
    Subtitle = RouteId + 2
    Group = RouteId + 3
    RendererKind = RouteId + 4
    Operational = RouteId + 5


_ROLE_NAMES = {
    int(ShellRole.RouteId): QByteArray(b"routeId"),
    int(ShellRole.Title): QByteArray(b"title"),
    int(ShellRole.Subtitle): QByteArray(b"subtitle"),
    int(ShellRole.Group): QByteArray(b"group"),
    int(ShellRole.RendererKind): QByteArray(b"rendererKind"),
    int(ShellRole.Operational): QByteArray(b"operational"),
}


@dataclass(frozen=True, slots=True)
class _ShellRow:
    route_id: str
    title: str
    subtitle: str
    group: str
    renderer_kind: str
    operational: bool


def _rows() -> tuple[_ShellRow, ...]:
    home = _ShellRow(
        HOME_ROUTE_ID,
        HOME_TITLE,
        HOME_SUBTITLE,
        NAVIGATION_GROUP_ORDER[0],
        "home",
        True,
    )
    known = tuple(
        _ShellRow(
            descriptor.surface_id,
            descriptor.title,
            descriptor.subtitle,
            descriptor.navigation_group,
            descriptor.renderer_kind,
            descriptor.operational,
        )
        for group in NAVIGATION_GROUP_ORDER
        for descriptor in SURFACE_DESCRIPTORS
        if descriptor.navigation_group == group
    )
    grouped_ids = {row.route_id for row in known}
    more = tuple(
        _ShellRow(
            descriptor.surface_id,
            descriptor.title,
            descriptor.subtitle,
            "More",
            descriptor.renderer_kind,
            descriptor.operational,
        )
        for descriptor in SURFACE_DESCRIPTORS
        if descriptor.surface_id not in grouped_ids
    )
    return (home,) + known + more


class ShellRegistryModel(QAbstractListModel):
    def __init__(self, parent: Any | None = None) -> None:
        super().__init__(parent)
        self._rows = _rows()
        self._group_order = tuple(NAVIGATION_GROUP_ORDER)
        self._home_tiles = tuple(
            {
                "routeId": item.surface_id,
                "title": item.title,
                "iconKey": item.icon_key,
                "subtitle": item.subtitle,
            }
            for item in HOME_HUB_TILES
        )
        self._shortcuts = tuple(
            {"key": key, "label": label}
            for key, label in QT_QUICK_SHORTCUT_ACTIONS
        )
        self._routes = tuple(
            {
                "routeId": row.route_id,
                "title": row.title,
                "subtitle": row.subtitle,
                "group": row.group,
                "rendererKind": row.renderer_kind,
                "operational": row.operational,
            }
            for row in self._rows
        )

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        values = {
            int(ShellRole.RouteId): row.route_id,
            int(ShellRole.Title): row.title,
            int(ShellRole.Subtitle): row.subtitle,
            int(ShellRole.Group): row.group,
            int(ShellRole.RendererKind): row.renderer_kind,
            int(ShellRole.Operational): row.operational,
        }
        return values.get(role)

    def roleNames(self) -> dict[int, QByteArray]:
        return dict(_ROLE_NAMES)

    @Property(int, constant=True)
    def count(self) -> int:
        return len(self._rows)

    @Property("QVariantList", constant=True)
    def groupOrder(self) -> list[str]:
        return list(self._group_order)

    @Property("QVariantList", constant=True)
    def homeTiles(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._home_tiles]

    @Property("QVariantList", constant=True)
    def shortcuts(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._shortcuts]

    @Property(bool, constant=True)
    def hasMore(self) -> bool:
        return any(row.group == "More" for row in self._rows)

    @Property("QVariantList", constant=True)
    def routes(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._routes]

    @Property(int, constant=True)
    def homeTileCount(self) -> int:
        return len(self._home_tiles)
