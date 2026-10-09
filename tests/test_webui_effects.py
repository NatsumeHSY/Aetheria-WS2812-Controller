import unittest
import urllib.error
import urllib.request
from pathlib import Path

from client.webui.webui import BlankPageServer, JavaScriptBridge


ROOT = Path(__file__).resolve().parents[1]


class FakeController:
    def __init__(self):
        self.calls = []

    def fill(self, color, brightness):
        self.calls.append(("fill", color, brightness))
        return 1

    def breathe(self, colors, dark_brightness, bright_brightness):
        self.calls.append(("breathe", list(colors), dark_brightness, bright_brightness))
        return 2

    def rainbow(self, **kwargs):
        self.calls.append(("rainbow", kwargs))
        return 3


def bridge_with_fake_controller():
    bridge = JavaScriptBridge.__new__(JavaScriptBridge)
    bridge.controller = FakeController()
    return bridge


class WebUiEffectTests(unittest.TestCase):
    def test_breathe_uses_all_selected_colors(self):
        bridge = bridge_with_fake_controller()

        bridge._apply_mode({
            "color": "#010203",
            "colors": ["#112233", "#445566"],
            "brightness": 80,
            "speed": 50,
            "mode": "呼吸渐变",
        })

        self.assertEqual(
            bridge.controller.calls,
            [("breathe", [(17, 34, 51), (68, 85, 102)], 0, 204)],
        )

    def test_single_color_mode_uses_first_color(self):
        bridge = bridge_with_fake_controller()

        bridge._apply_mode({
            "color": "#010203",
            "colors": ["#112233", "#445566"],
            "brightness": 80,
            "speed": 50,
            "mode": "静态常亮",
        })

        self.assertEqual(bridge.controller.calls, [("fill", (17, 34, 51), 204)])

    def test_rainbow_mode_uses_firmware_effect_without_client_colors(self):
        bridge = bridge_with_fake_controller()

        bridge._apply_mode({
            "color": "#010203",
            "colors": ["#112233", "#445566"],
            "brightness": 80,
            "speed": 50,
            "mode": "流光溢彩",
        })

        self.assertEqual(
            bridge.controller.calls,
            [("rainbow", {
                "brightness": 204,
                "interval": 5,
                "duration": 5,
                "pingpong": True,
            })],
        )

    def test_ui_removes_neon_mode_and_exposes_color_list_controls(self):
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        runtime_index = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")
        controller = (ROOT / "client" / "controller.py").read_text(encoding="utf-8")
        board = (ROOT / "board" / "main.py").read_text(encoding="utf-8")

        self.assertNotIn("霓虹闪烁", template)
        self.assertNotIn("霓虹闪烁", runtime_constants)
        self.assertIn("addColor", template)
        self.assertIn("addColor", runtime_constants)
        self.assertIn("removeColor", runtime_index)
        self.assertIn('b"\\x05": led_rainbow', board)
        self.assertNotIn('b"\\x05": led_scan_line_x', board)
        self.assertNotIn('b"\\x09": led_rainbow', board)
        self.assertNotIn("def scan_line_x(", controller)

    def test_palette_list_has_fixed_scroll_area_and_full_width_default_row(self):
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")

        for source in (template, runtime_constants):
            self.assertIn(".palette-row.removable", source)
            self.assertIn("height: 184px", source)
            self.assertIn("overflow-y: scroll", source)
            self.assertRegex(source, r"border: (1px solid var\(--line\)|2px solid #00ffff)")
            self.assertIn("align-content: start", source)

    def test_ui_brand_status_has_no_output_source_selector(self):
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")

        for source in (template, runtime_constants):
            self.assertIn("AETHERIA DESKTOP/CLOUD LED", source)
            self.assertNotIn("NATSUME LAB / LIGHT DESK", source)
            self.assertNotIn("柔光控制台", source)
            self.assertNotIn("source-button", source)
            self.assertNotIn("source-switch", source)
            self.assertNotIn("sourceValue", source)
            self.assertNotIn("输出方式", source)

        self.assertNotIn('class="mode-button" type="button">自定义矩阵</button>', template)
        self.assertNotIn('class="mode-btn pixel-btn">自定义矩阵</button>', runtime_constants)
        self.assertNotIn("逻辑坐标", template)

    def test_palette_action_buttons_share_common_tool_button_states(self):
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")

        self.assertIn(".tool-button:hover", template)
        self.assertIn(".tool-button:hover", runtime_constants)
        self.assertIn(".tool-button:active", template)
        self.assertIn(".tool-button:active", runtime_constants)
        self.assertNotIn(".device-action:hover", template)
        self.assertNotIn(".device-action:hover", runtime_constants)
        self.assertIn(".palette-remove:hover", runtime_constants)
        self.assertIn(".palette-add:active", runtime_constants)

    def test_runtime_uses_compact_synced_ui_source(self):
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        webui_source = (ROOT / "client" / "webui" / "webui.py").read_text(encoding="utf-8")
        asset = ROOT / "client" / "webui" / "assets" / "background.png"

        self.assertIn("AETHERIA DESKTOP/CLOUD LED", runtime_constants)
        self.assertNotIn("source-button", runtime_constants)
        self.assertNotIn("自定义矩阵", runtime_constants)
        self.assertNotIn("NATSUME LAB / LIGHT DESK", runtime_constants)
        self.assertNotIn("柔光控制台", runtime_constants)
        self.assertNotIn("PixelFontBase64Data", runtime_constants)
        self.assertNotIn("data:image/png;base64", runtime_constants)
        self.assertIn('runtime_const.js', webui_source)
        self.assertTrue(asset.exists())
        self.assertGreater(asset.stat().st_size, 1000)

    def test_runtime_uses_parameter_commands_for_live_controls(self):
        runtime_index = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")

        self.assertIn('bridgeCall("set_brightness"', runtime_index)
        self.assertIn('bridgeCall("set_timing"', runtime_index)
        self.assertIn("function updateBrightnessParameter", runtime_index)
        self.assertIn("function updateTimingParameter", runtime_index)
        self.assertNotIn('brightness.addEventListener("input", () => {\n        document.getElementById("brightValue").textContent = `${brightness.value}%`;\n        applyCurrentSettings();', runtime_index)

    def test_white_balance_controls_are_kept_in_preview_and_runtime_sources(self):
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        runtime_index = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")

        for source in (template, runtime_constants):
            self.assertIn('id="whiteBalanceRed"', source)
            self.assertIn('id="whiteBalanceGreen"', source)
            self.assertIn('id="whiteBalanceBlue"', source)
            self.assertIn('id="resetWhiteBalance"', source)
            self.assertIn("white-balance-grid", source)
        self.assertIn('bridgeCall("set_white_balance"', runtime_index)
        self.assertIn("whiteBalance: getWhiteBalanceValues()", runtime_index)
        self.assertIn("applyWhiteBalanceControls(state.whiteBalance)", runtime_index)

    def test_blank_page_server_serves_loopback_shell_and_stops(self):
        server = BlankPageServer()
        url = server.start()
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                body = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "text/html")
                self.assertIn("<body></body>", body)
                self.assertTrue(url.startswith("http://127.0.0.1:"))
        finally:
            server.stop()

        with self.assertRaises(urllib.error.URLError):
            urllib.request.urlopen(url, timeout=1)

    def test_blank_page_server_serves_background_asset(self):
        asset = ROOT / "client" / "webui" / "assets" / "background.png"
        server = BlankPageServer(asset)
        url = server.start()
        try:
            with urllib.request.urlopen(f"{url}background.png", timeout=1) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "image/png")
                self.assertEqual(response.read(8), b"\x89PNG\r\n\x1a\n")
        finally:
            server.stop()

    def test_preview_badge_is_removed_and_ui_signals_ready(self):
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        runtime_index = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")

        for source in (template, runtime_constants):
            self.assertNotIn("预览模式", source)
            self.assertNotIn("预览中", source)
        self.assertIn("ui_ready", runtime_index)

    def test_webview_injects_on_loaded_and_uses_http_shell(self):
        webui_source = (ROOT / "client" / "webui" / "webui.py").read_text(encoding="utf-8")

        self.assertIn("BlankPageServer", webui_source)
        self.assertIn("self.window.events.loaded", webui_source)
        self.assertNotIn("self.window.events.shown += self._inject_scripts", webui_source)
        self.assertIn("background.png", webui_source)
        self.assertNotIn("background.as_uri()", webui_source)
        self.assertIn("ui_ready", webui_source)
        self.assertIn("self._blank_server.stop()", webui_source)

    def test_shape_panel_and_formal_topbar_status_exist_in_runtime_and_preview(self):
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")

        for source in (template, runtime_constants):
            self.assertIn('id="shapeList"', source)
            self.assertIn('id="saveShape"', source)
            self.assertIn('id="shapeName"', source)
            self.assertIn("connectionStatus", source)
            self.assertIn("connectionState", source)
            self.assertIn("heartbeatAge", source)
            self.assertIn("statusMessage", source)
            self.assertIn('aria-live="polite"', source)
            self.assertNotIn('<footer class="status-bar">', source)


if __name__ == "__main__":
    unittest.main()
