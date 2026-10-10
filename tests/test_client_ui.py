from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ClientUiTests(unittest.TestCase):
    def test_preview_invert_uses_matrix_paint_color(self) -> None:
        source = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        block = re.search(
            r'document\.getElementById\("invertMatrix"\).*?\n\s*\}\);',
            source,
            re.S,
        )
        self.assertIsNotNone(block)
        self.assertIn('value === "#000000" ? paintColorPicker.value', block.group(0))

    def test_runtime_invert_uses_matrix_paint_color(self) -> None:
        source = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")
        block = re.search(
            r'document\.getElementById\("invertMatrix"\).*?\n\s*\}\);',
            source,
            re.S,
        )
        self.assertIsNotNone(block)
        self.assertIn('value === "#000000" ? paintColorPicker.value', block.group(0))

    def test_runtime_has_shape_library_and_health_status_workflow(self) -> None:
        source = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")
        for symbol in (
            "loadShapes",
            "renderShapeList",
            "sendShape",
            "loadShape",
            "saveCurrentShape",
            "updateCurrentShape",
            "deleteShape",
            "startHealthMonitor",
            "renderConnectionStatus",
        ):
            self.assertIn(f"function {symbol}", source)
        for action in ("shape-send", "shape-load", "shape-update", "shape-delete"):
            self.assertIn(action, source)
        self.assertIn('bridgeCall("health")', source)
        self.assertIn("heartbeatAge", source)
        self.assertIn("setInterval", source)
        self.assertIn('getElementById("connectionStatus")', source)
        self.assertIn('getElementById("statusMessage")', source)
        self.assertNotIn('querySelector(".status-bar span")', source)

    def test_status_surfaces_separate_canvas_and_device_state(self) -> None:
        runtime = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        preview = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        index = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")

        for source in (runtime, preview):
            self.assertIn('id="matrixState"', source)
            self.assertIn("画布就绪", source)
            self.assertNotIn('id="matrixDeviceStatus"', source)

        self.assertIn('getElementById("matrixState")', index)
        self.assertIn("function setMatrixState", index)
        self.assertIn('setMatrixState("画布已清空")', index)
        self.assertIn('setMatrixState("画布颜色已反转")', index)
        self.assertIn('setMatrixState("矩阵已发送")', index)
        self.assertNotIn('getElementById("matrixDeviceStatus")', index)
        self.assertNotIn('setStatus("画布已清空"', index)
        self.assertNotIn('setStatus("画布颜色已反转"', index)

    def test_shape_library_fills_panel_and_uses_uniform_preview_grid(self) -> None:
        runtime = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        preview = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        for source in (runtime, preview):
            self.assertIn(".matrix-panel { display: flex; flex-direction: column;", source)
            self.assertIn(".shape-panel { display: flex; flex: 1; min-height: 0;", source)
            self.assertIn(".shape-list { display: grid; flex: 1;", source)
            self.assertIn("overflow-y: scroll", source)
            self.assertIn("align-content: start", source)
            self.assertNotIn("grid-auto-rows: minmax(120px, 1fr)", source)
            self.assertNotIn("max-height: 236px", source)
            self.assertIn("grid-template-columns: repeat(24, minmax(0, 1fr))", source)
            self.assertIn("grid-template-rows: repeat(6, minmax(0, 1fr))", source)
            self.assertIn(".shape-preview-cell {", source)
            self.assertIn("width: 100%; height: 100%", source)
            self.assertIn(".shape-card-body strong {", source)
            self.assertIn("font-size: 11px", source)

    def test_health_failure_shows_offline_message_and_retries_handshake(self) -> None:
        source = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")
        monitor = re.search(r"function startHealthMonitor\(\).*?\n\}\n\nfunction bindEvents", source, re.S)
        self.assertIsNotNone(monitor)
        monitor_source = monitor.group(0)
        self.assertIn('bridgeCall("connect")', monitor_source)
        self.assertIn("reconnecting", monitor_source)
        self.assertIn('"心跳未收到"', source)
        self.assertIn('connected === true ? "设备已响应" : "设备未连接"', source)

    def test_runtime_has_state_restore_sync_and_shutdown_persistence(self) -> None:
        source = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")
        for symbol in (
            "applyUiState",
            "applySyncedState",
            "restoreLocalState",
            "persistState",
            "flushPersistedState",
        ):
            self.assertIn(f"function {symbol}", source)
        self.assertIn('bridgeApiCall("load_state")', source)
        self.assertIn('bridgeApiCall("save_state"', source)
        self.assertIn('bridgeCall("sync")', source)
        self.assertIn("connection.recovered", source)
        self.assertIn('window.addEventListener("beforeunload"', source)

    def test_runtime_uses_theme_modal_for_all_native_dialog_flows(self) -> None:
        runtime = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        preview = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        index = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")

        for source in (runtime, preview):
            self.assertIn('id="appModal"', source)
            self.assertIn('id="modalTitle"', source)
            self.assertIn('id="modalMessage"', source)
            self.assertIn('id="modalInput"', source)
            self.assertIn(".modal-dialog", source)

        for symbol in ("openModal", "showNotice", "showConfirm", "showPrompt", "closeModal"):
            self.assertIn(f"function {symbol}", index)
        self.assertNotRegex(index, r"window\.(alert|confirm|prompt)\s*\(")
        self.assertIn("showPrompt(", index)
        self.assertIn("showConfirm(", index)
        self.assertIn("showNotice(", index)

    def test_runtime_persists_output_source_paint_color_and_preserves_rainbow_palette(self) -> None:
        source = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")
        settings = re.search(r"function currentSettings\(\).*?\n\}", source, re.S)
        self.assertIsNotNone(settings)
        self.assertIn("source", settings.group(0))
        self.assertIn("paintColor", settings.group(0))
        self.assertIn('state.mode === "流光溢彩"', source)
        self.assertIn("fallback.colors", source)
        self.assertIn("fallback.paintColor", source)

    def test_audio_response_mode_and_status_polling_are_dynamic_and_themed(self) -> None:
        runtime = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        preview = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        index = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")

        for source in (runtime, preview):
            self.assertIn("音频响应", source)
            self.assertIn('id="audioResponseStatus"', source)
            self.assertIn('id="audioBandLow"', source)
            self.assertIn('id="audioBandMid"', source)
            self.assertIn('id="audioBandHigh"', source)

        for symbol in ("renderAudioStatus", "startAudioStatusMonitor", "stopAudioStatusMonitor"):
            self.assertIn(f"function {symbol}", index)
        self.assertIn('bridgeApiCall("audio_status")', index)
        self.assertIn("startAudioStatusMonitor", index)
        self.assertIn("stopAudioStatusMonitor", index)


if __name__ == "__main__":
    unittest.main()
