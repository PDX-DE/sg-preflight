from __future__ import annotations

import unittest

try:
    from PySide6.QtCore import QModelIndex, Qt
except ModuleNotFoundError as error:
    if error.name != "PySide6":
        raise
    raise unittest.SkipTest("PySide6 is not installed") from error

from sg_preflight.shell_registry import HOME_ROUTE_ID, NAVIGATION_GROUP_ORDER
from sg_preflight.surface_registry import SURFACE_DESCRIPTORS


class TestSurfaceRegistryModel(unittest.TestCase):
    def setUp(self) -> None:
        from sg_preflight.desktop.surface_model import SurfaceRegistryModel

        self.model = SurfaceRegistryModel()
        self.role_items = tuple(
            (int(role), bytes(name)) for role, name in self.model.roleNames().items()
        )

    def test_roles_use_the_exact_qml_names_and_integer_sequence(self) -> None:
        from sg_preflight.desktop.surface_model import SurfaceRole

        first_role = int(Qt.ItemDataRole.UserRole) + 1
        expected_enum = (
            ("SurfaceId", first_role),
            ("Title", first_role + 1),
            ("Subtitle", first_role + 2),
            ("Group", first_role + 3),
            ("RendererKind", first_role + 4),
            ("Operational", first_role + 5),
        )
        expected_roles = (
            (first_role, b"surfaceId"),
            (first_role + 1, b"title"),
            (first_role + 2, b"subtitle"),
            (first_role + 3, b"group"),
            (first_role + 4, b"rendererKind"),
            (first_role + 5, b"operational"),
        )

        self.assertEqual(tuple((role.name, int(role)) for role in SurfaceRole), expected_enum)
        self.assertEqual(self.role_items, expected_roles)

    def test_constructor_snapshots_mutable_descriptor_sequences(self) -> None:
        from sg_preflight.desktop.surface_model import SurfaceRegistryModel, SurfaceRole

        source_descriptors = list(SURFACE_DESCRIPTORS[:2])
        model = SurfaceRegistryModel(source_descriptors)

        source_descriptors.clear()

        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(
            model.data(model.index(1, 0), int(SurfaceRole.SurfaceId)),
            SURFACE_DESCRIPTORS[1].surface_id,
        )

    def test_rows_project_every_descriptor_value_in_stable_order(self) -> None:
        expected_rows = tuple(
            (
                descriptor.surface_id,
                descriptor.title,
                descriptor.subtitle,
                descriptor.navigation_group,
                descriptor.renderer_kind,
                descriptor.operational,
            )
            for descriptor in SURFACE_DESCRIPTORS
        )
        actual_rows = tuple(
            tuple(
                self.model.data(self.model.index(row, 0), role)
                for role, _name in self.role_items
            )
            for row in range(self.model.rowCount())
        )

        self.assertIs(type(SURFACE_DESCRIPTORS), tuple)
        self.assertEqual(self.model.rowCount(), 19)
        self.assertEqual(self.model.count, 19)
        self.assertEqual(actual_rows, expected_rows)
        self.assertNotIn(HOME_ROUTE_ID, tuple(row[0] for row in actual_rows))
        self.assertEqual({row[3] for row in actual_rows}, set(NAVIGATION_GROUP_ORDER))
        self.assertIn("Delivery", {row[3] for row in actual_rows})

    def test_invalid_indexes_roles_and_default_display_role_return_none(self) -> None:
        first_role = self.role_items[0][0]
        first_index = self.model.index(0, 0)
        out_of_range_index = self.model.createIndex(self.model.rowCount(), 0)

        self.assertTrue(first_index.isValid())
        self.assertTrue(out_of_range_index.isValid())
        self.assertIsNone(self.model.data(QModelIndex(), first_role))
        self.assertIsNone(self.model.data(out_of_range_index, first_role))
        self.assertIsNone(self.model.data(first_index, int(Qt.ItemDataRole.UserRole) + 99))
        self.assertIsNone(self.model.data(first_index))

    def test_valid_parent_has_no_rows(self) -> None:
        parent = self.model.index(0, 0)

        self.assertTrue(parent.isValid())
        self.assertEqual(self.model.rowCount(parent), 0)

    def test_count_property_is_constant_and_model_has_no_mutation_slots(self) -> None:
        meta_object = self.model.metaObject()
        count_property = meta_object.property(meta_object.indexOfProperty("count"))
        own_methods = tuple(
            bytes(meta_object.method(index).methodSignature())
            for index in range(meta_object.methodOffset(), meta_object.methodCount())
        )

        self.assertTrue(count_property.isValid())
        self.assertTrue(count_property.isReadable())
        self.assertTrue(count_property.isConstant())
        self.assertFalse(count_property.isWritable())
        self.assertEqual(count_property.read(self.model), 19)
        self.assertEqual(own_methods, ())


if __name__ == "__main__":
    unittest.main()
