import json
import tempfile
import unittest
from pathlib import Path

from client.matrix_shapes import MatrixShapeStore, materialize_preset, preset_shapes, validate_matrix


def blank_matrix(color="#000000"):
    return [[color for _ in range(144)] for _ in range(6)]


class MatrixShapeStoreTests(unittest.TestCase):
    def test_preset_shapes_are_six_read_only_masks_with_expected_dimensions(self):
        shapes = preset_shapes()

        self.assertEqual(len(shapes), 6)
        self.assertTrue(all(shape["kind"] == "preset" for shape in shapes))
        self.assertTrue(all(shape["editable"] is False for shape in shapes))
        self.assertTrue(all(len(shape["matrix"]) == 6 for shape in shapes))
        self.assertTrue(all(len(row) == 144 for shape in shapes for row in shape["matrix"]))

    def test_preset_materialization_uses_requested_color(self):
        mask = [[0 for _ in range(144)] for _ in range(6)]
        mask[2][17] = 1

        matrix = materialize_preset(mask, "#123456")

        self.assertEqual(matrix[2][17], "#123456")
        self.assertEqual(matrix[0][0], "#000000")

    def test_user_shape_persists_and_supports_update_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix_shapes.json"
            store = MatrixShapeStore(path)
            original = blank_matrix("#112233")
            updated = blank_matrix("#445566")

            shape = store.save_user_shape("My star", original)
            reloaded = MatrixShapeStore(path)

            self.assertEqual(reloaded.get_shape(shape["id"])["matrix"], original)
            changed = reloaded.update_user_shape(shape["id"], "Updated", updated)
            self.assertEqual(changed["name"], "Updated")
            self.assertEqual(changed["matrix"], updated)

            reloaded.delete_user_shape(shape["id"])
            self.assertIsNone(reloaded.get_shape(shape["id"]))

    def test_invalid_matrix_and_preset_mutation_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MatrixShapeStore(Path(directory) / "matrix_shapes.json")
            preset = preset_shapes()[0]

            with self.assertRaises(ValueError):
                validate_matrix([["#ffffff"]])
            with self.assertRaises(ValueError):
                store.save_user_shape("", blank_matrix())
            with self.assertRaises(ValueError):
                store.update_user_shape(preset["id"], "Nope", blank_matrix())
            with self.assertRaises(ValueError):
                store.delete_user_shape(preset["id"])

    def test_corrupt_storage_is_treated_as_empty_user_shape_list(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix_shapes.json"
            path.write_text("not json", encoding="utf-8")

            store = MatrixShapeStore(path)

            self.assertEqual(len(store.list_shapes()), 6)
            matrix = blank_matrix()
            matrix[0][0] = "#ffffff"
            store.save_user_shape("Recovered", matrix)
            json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
