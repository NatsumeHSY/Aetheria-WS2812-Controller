import tempfile
import unittest
from pathlib import Path

from client.matrix_shapes import MatrixShapeStore, preset_shapes
from client.sync_state import SyncSnapshot
from client.ui_state import UiStateStore
from client.controller import ControllerError
from client.webui.webui import JavaScriptBridge


def lit_matrix(color="#112233"):
    matrix = [["#000000" for _ in range(144)] for _ in range(6)]
    matrix[0][0] = color
    return matrix


class ShapeBridgeController:
    def __init__(self):
        self.connected = True
        self.calls = []

    def health(self):
        self.calls.append(("health",))
        return True

    def clear(self):
        self.calls.append(("clear",))
        return 10

    def set_pixels(self, pixels, coordinate_mode=True):
        self.calls.append(("set_pixels", list(pixels), coordinate_mode))
        return 11

    def show(self):
        self.calls.append(("show",))
        return 12

    def set_white_balance(self, red, green, blue):
        self.calls.append(("white_balance", red, green, blue))
        return 13


class SyncBridgeController(ShapeBridgeController):
    def __init__(self, snapshot=None, error=None):
        super().__init__()
        self.last_connect_recovered = True
        self.snapshot = snapshot
        self.error = error

    def connect(self):
        self.calls.append(("connect",))
        return True

    def sync(self):
        self.calls.append(("sync",))
        if self.error:
            raise self.error
        return self.snapshot


class WebUiBridgeTests(unittest.TestCase):
    def make_bridge(self, store):
        bridge = JavaScriptBridge.__new__(JavaScriptBridge)
        bridge.controller = ShapeBridgeController()
        bridge.shape_store = store
        bridge.ui_state_store = UiStateStore(store.path.parent / "ui_state.json")
        return bridge

    def test_health_returns_connected_state(self):
        bridge = self.make_bridge(MatrixShapeStore(Path(tempfile.mkdtemp()) / "shapes.json"))

        self.assertEqual(bridge.health(), {"ok": True, "connected": True})
        self.assertEqual(bridge.controller.calls, [("health",)])

    def test_white_balance_is_exposed_through_bridge(self):
        bridge = self.make_bridge(MatrixShapeStore(Path(tempfile.mkdtemp()) / "shapes.json"))

        result = bridge.set_white_balance("255", 190, 110)

        self.assertEqual(
            result,
            {
                "ok": True,
                "connected": True,
                "sequence": 13,
                "whiteBalance": [255, 190, 110],
            },
        )
        self.assertEqual(bridge.controller.calls, [("white_balance", 255, 190, 110)])

    def test_shape_crud_is_exposed_through_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))
            shape = bridge.save_shape("User", lit_matrix())

            self.assertTrue(shape["ok"])
            shape_id = shape["shape"]["id"]
            changed = bridge.update_shape(shape_id, "Changed", lit_matrix("#445566"))
            self.assertEqual(changed["shape"]["name"], "Changed")
            self.assertEqual(bridge.delete_shape(shape_id), {"ok": True})

    def test_preset_send_uses_paint_color_and_current_brightness(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))
            preset = preset_shapes()[0]

            result = bridge.send_shape(preset["id"], 180, "#123456")

            self.assertEqual(result, {"ok": True, "connected": True, "sequence": 12})
            set_pixels = next(call for call in bridge.controller.calls if call[0] == "set_pixels")
            self.assertEqual(set_pixels[1][0][2:], (180, 0x12, 0x34, 0x56))

    def test_shape_errors_are_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))

            result = bridge.update_shape("preset-horizontal", "Nope", lit_matrix())

            self.assertFalse(result["ok"])
            self.assertIn("error", result)

    def test_connect_exposes_recovered_session_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))
            bridge.controller = SyncBridgeController()

            self.assertEqual(
                bridge.connect(),
                {"ok": True, "connected": True, "recovered": True},
            )

    def test_sync_maps_board_static_and_matrix_state_to_ui_state(self):
        snapshot = SyncSnapshot(1, 25, 200, 0, ((17, 34, 51),), None, (255, 190, 110))
        matrix = tuple(
            tuple((1, 2, 3) if row == 0 and column == 0 else (0, 0, 0) for column in range(144))
            for row in range(6)
        )
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))
            bridge.controller = SyncBridgeController(snapshot=snapshot)

            result = bridge.sync()

            self.assertTrue(result["ok"])
            self.assertEqual(result["state"]["mode"], "静态常亮")
            self.assertEqual(result["state"]["brightness"], round(200 * 100 / 255))
            self.assertEqual(result["state"]["colors"], ["#112233"])
            self.assertEqual(result["state"]["whiteBalance"], [255, 190, 110])

            bridge.controller.snapshot = SyncSnapshot(4, 80, 80, 0, (), matrix)
            matrix_result = bridge.sync()
            self.assertEqual(matrix_result["state"]["source"], "matrix")
            self.assertEqual(matrix_result["state"]["mode"], "自定义矩阵")
            self.assertEqual(matrix_result["state"]["matrix144x6"][0][0], "#010203")

    def test_sync_rainbow_does_not_invent_client_palette_colors(self):
        snapshot = SyncSnapshot(3, 0, 180, 20, (), None)
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))
            bridge.controller = SyncBridgeController(snapshot=snapshot)

            result = bridge.sync()

            self.assertTrue(result["ok"])
            self.assertEqual(result["state"]["mode"], "流光溢彩")
            self.assertEqual(result["state"]["colors"], [])

    def test_sync_flow_effect_uses_fixed_ui_rhythm_value(self):
        snapshot = SyncSnapshot(3, 0, 180, 1, (), None)
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))
            bridge.controller = SyncBridgeController(snapshot=snapshot)

            self.assertEqual(bridge.sync()["state"]["speed"], 50)

    def test_sync_format_error_keeps_transport_connected(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))
            bridge.controller = SyncBridgeController(error=ControllerError("bad sync"))

            result = bridge.sync()

            self.assertEqual(result["connected"], True)
            self.assertFalse(result["ok"])

    def test_state_load_save_is_exposed_through_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = self.make_bridge(MatrixShapeStore(Path(directory) / "shapes.json"))
            state = {
                "version": 1,
                "source": "quick",
                "mode": "静态常亮",
                "brightness": 72,
                "speed": 50,
                "colors": ["#112233"],
                "paintColor": "#8dc9bc",
                "matrix144x6": lit_matrix(),
            }

            saved = bridge.save_state(state)

            self.assertTrue(saved["ok"])
            self.assertEqual(bridge.load_state()["state"], saved["state"])
            self.assertFalse(bridge.save_state({"version": 99})["ok"])


if __name__ == "__main__":
    unittest.main()
