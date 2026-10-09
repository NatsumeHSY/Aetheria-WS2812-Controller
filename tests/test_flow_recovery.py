import unittest
from pathlib import Path

from client.controller import LEDController
from client.ui_state import normalize_ui_state
from client.webui.webui import JavaScriptBridge


ROOT = Path(__file__).resolve().parents[1]


class FakeEffectController:
    def __init__(self):
        self.calls = []

    def rainbow(self, **kwargs):
        self.calls.append(("rainbow", kwargs))
        return 3


class FlowRecoveryTests(unittest.TestCase):
    def test_controller_exposes_rainbow_effect_command(self):
        controller = LEDController.__new__(LEDController)
        controller._send_packet = lambda command, payload: (command, bytes(payload))

        command, payload = controller.rainbow(
            brightness=204,
            interval=20,
            duration=20,
            pingpong=True,
        )

        self.assertEqual(command, 0x05)
        self.assertEqual(payload, b"\x00\x8f\xcc\x00\x14\x00\x14\xff")
        self.assertFalse(hasattr(controller, "rainbow_line_x"))

    def test_legacy_saved_rainbow_mode_normalizes_to_new_label(self):
        state = {
            "version": 1,
            "source": "quick",
            "mode": "彩虹跑马",
            "brightness": 80,
            "speed": 50,
            "colors": ["#112233"],
            "paintColor": "#445566",
            "matrix144x6": [["#000000" for _ in range(144)] for _ in range(6)],
        }

        self.assertEqual(normalize_ui_state(state)["mode"], "流光溢彩")

    def test_bridge_maps_flow_effect_to_controller_rainbow(self):
        bridge = JavaScriptBridge.__new__(JavaScriptBridge)
        bridge.controller = FakeEffectController()

        bridge._apply_mode({
            "colors": ["#112233", "#445566"],
            "brightness": 80,
            "speed": 50,
            "mode": "流光溢彩",
        })

        self.assertEqual(bridge.controller.calls, [(
            "rainbow",
            {
                "brightness": 204,
                "interval": 5,
                "duration": 5,
                "pingpong": True,
            },
        )])

    def test_bridge_ignores_speed_changes_for_flow_effect(self):
        bridge = JavaScriptBridge.__new__(JavaScriptBridge)
        bridge.controller = FakeEffectController()

        for speed in (10, 200):
            bridge._apply_mode({
                "colors": ["#112233"],
                "brightness": 80,
                "speed": speed,
                "mode": "流光溢彩",
            })

        self.assertEqual(bridge.controller.calls[0], bridge.controller.calls[1])

    def test_runtime_keeps_global_rhythm_control_available_for_flow_effect(self):
        source = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")

        self.assertIn("function updateRhythmControl", source)
        self.assertNotIn("speed.disabled", source)
        self.assertNotIn("流光固定", template)
        self.assertNotIn("流光固定", runtime_constants)
        self.assertNotIn('if (activeMode === "流光溢彩" || activeMode === "彩虹跑马") return;', source)
        self.assertIn('bridgeCall("set_timing", timingMs)', source)

    def test_board_rainbow_uses_fixed_smooth_timing(self):
        board = "\n".join(
            (ROOT / "board" / name).read_text(encoding="utf-8")
            for name in ("main.py", "config.py", "effects.py")
        )

        self.assertIn("RAINBOW_FRAME_INTERVAL = 5", board)
        self.assertIn("RAINBOW_HUE_STEP = 1", board)
        self.assertIn("RAINBOW_HUE_DIVISOR = 2", board)
        self.assertIn("time.sleep_ms(RAINBOW_FRAME_INTERVAL)", board)
        self.assertIn("hue_phase += RAINBOW_HUE_STEP", board)
        self.assertIn("hue_offset = (hue_phase // RAINBOW_HUE_DIVISOR) % 256", board)

    def test_client_source_has_explicit_maintenance_recovery_and_sync(self):
        source = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")

        self.assertIn("async function restoreConnection", source)
        self.assertIn('button.textContent = "恢复连接"', source)
        self.assertIn('const synced = await bridgeCall("sync")', source)
        self.assertIn("maintenanceMode = false", source)
        self.assertIn("正在重新握手", source)
        self.assertIn('"流光溢彩"', source)

    def test_board_and_client_use_rainbow_name_without_legacy_effect_name(self):
        board = "\n".join(
            (ROOT / "board" / name).read_text(encoding="utf-8")
            for name in ("main.py", "config.py", "effects.py")
        )
        controller = (ROOT / "client" / "controller.py").read_text(encoding="utf-8")
        bridge = (ROOT / "client" / "webui" / "webui.py").read_text(encoding="utf-8")

        self.assertIn("def rainbow(", board)
        self.assertIn("def led_rainbow(", board)
        self.assertIn("def rainbow(", controller)
        self.assertIn("self.controller.rainbow(", bridge)
        self.assertNotIn("rainbow_line_x", board + controller + bridge)


if __name__ == "__main__":
    unittest.main()
