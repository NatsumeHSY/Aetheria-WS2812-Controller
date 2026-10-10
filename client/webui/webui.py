from __future__ import annotations

import json
import os
import threading
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import webview

try:
    from controller import ControllerError, LEDController
    from matrix_shapes import MatrixShapeStore, materialize_preset
    from media_color import MEDIA_MODE, MediaColorEffect, transition_duration_for_speed, transition_duration_for_timing
    from ui_state import UiStateStore, normalize_ui_state
    from utils import ConfigLoader
except ImportError:
    from ..controller import ControllerError, LEDController
    from ..matrix_shapes import MatrixShapeStore, materialize_preset
    from ..media_color import MEDIA_MODE, MediaColorEffect, transition_duration_for_speed, transition_duration_for_timing
    from ..ui_state import UiStateStore, normalize_ui_state
    from ..utils import ConfigLoader


CLIENT_DIR = Path(__file__).resolve().parents[1]
RAINBOW_FRAME_INTERVAL = 5


class _BlankPageHandler(BaseHTTPRequestHandler):
    _BODY = b"<!doctype html><html><head><meta charset=\"utf-8\"></head><body></body></html>"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/background.png":
            background = getattr(self.server, "background_path", None)
            if background is None or not background.is_file():
                self.send_error(404)
                return
            self._send_bytes(background.read_bytes(), "image/png")
            return
        if path != "/":
            self.send_error(404)
            return

        self._send_bytes(self._BODY, "text/html; charset=utf-8")

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class BlankPageServer:
    """Serve a temporary document so pywebview can reliably emit ``loaded``."""

    def __init__(self, background_path: Path | None = None) -> None:
        self._background_path = background_path
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        if self._server is not None:
            host, port = self._server.server_address
            return f"http://{host}:{port}/"

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _BlankPageHandler)
        self._server.background_path = self._background_path
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="webview-blank-page-server",
            daemon=True,
        )
        self._thread.start()
        host, port = self._server.server_address
        return f"http://{host}:{port}/"

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None

        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)


def _hex_color(value: str) -> tuple[int, int, int]:
    value = str(value).lstrip("#")
    if len(value) != 6:
        raise ValueError("color must be a six-digit hexadecimal value")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _brightness(value: int | str) -> int:
    return max(0, min(255, round(int(value) * 255 / 100)))


def _settings_colors(settings: dict) -> list[tuple[int, int, int]]:
    values = settings.get("colors")
    if not isinstance(values, list) or not values:
        values = [settings.get("color", "#ff0080")]
    return [_hex_color(value) for value in values]


def _rgb_hex(color: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % tuple(int(channel) for channel in color)


def _blank_ui_matrix() -> list[list[str]]:
    return [["#000000" for _ in range(144)] for _ in range(6)]


class JavaScriptBridge:
    def __init__(self, config: dict | None = None):
        config = config or ConfigLoader("config.json").read_config()
        device = config.get("device", {})
        self.controller = LEDController(
            host=device.get("host", "192.168.4.1"),
            port=device.get("port", 7807),
            timeout=device.get("timeout", 0.5),
            retries=device.get("retries", 3),
        )
        self.shape_store = MatrixShapeStore(CLIENT_DIR / "configs" / "matrix_shapes.json")
        self.ui_state_store = UiStateStore(CLIENT_DIR / "configs" / "ui_state.json")
        self.media_effect = MediaColorEffect(self.controller)
        self._ui_ready_callback = None

    def _stop_media_effect(self) -> None:
        effect = getattr(self, "media_effect", None)
        if effect is not None:
            effect.deactivate()

    def media_status(self) -> dict:
        effect = getattr(self, "media_effect", None)
        return {
            "ok": True,
            "connected": self.controller.connected,
            "media": effect.status() if effect is not None else {"active": False},
        }

    def close(self) -> None:
        effect = getattr(self, "media_effect", None)
        if effect is not None:
            effect.close()
        self.controller.disconnect()

    def set_ui_ready_callback(self, callback) -> None:
        self._ui_ready_callback = callback

    def ui_ready(self) -> dict:
        if self._ui_ready_callback is not None:
            self._ui_ready_callback()
        return {"ok": True, "ready": True}

    def connect(self) -> dict:
        try:
            effect = getattr(self, "media_effect", None)
            if effect is not None:
                effect.suspend()
            connected = self.controller.connect()
            return {
                "ok": connected,
                "connected": connected,
                "recovered": bool(getattr(self.controller, "last_connect_recovered", False)) if connected else False,
            }
        except OSError as error:
            return {"ok": False, "connected": False, "recovered": False, "error": str(error)}

    def disconnect(self) -> dict:
        self._stop_media_effect()
        self.controller.disconnect()
        return {"ok": True, "connected": False}

    def enter_maintenance(self) -> dict:
        self._stop_media_effect()
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            sequence = self.controller.enter_maintenance()
            return {
                "ok": True,
                "connected": False,
                "maintenance": True,
                "sequence": sequence,
            }
        except (ControllerError, OSError, ValueError) as error:
            return {
                "ok": False,
                "connected": self.controller.connected,
                "error": str(error),
            }

    def health(self) -> dict:
        try:
            was_connected = self.controller.connected
            effect = getattr(self, "media_effect", None)
            if not was_connected and effect is not None:
                effect.suspend()
            connected = self.controller.health()
            if not connected and effect is not None:
                effect.suspend()
            result = {"ok": connected, "connected": connected}
            if connected and not was_connected:
                result["recovered"] = True
            return result
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": False, "error": str(error)}

    def set_brightness(self, value: int | str) -> dict:
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            effect = getattr(self, "media_effect", None)
            brightness = _brightness(value)
            # Invalidate an in-flight cover read atomically with its A0 ACK.
            # The worker takes this same lock before sending a transition.
            with effect.lock if effect is not None else nullcontext():
                sequence = self.controller.set_brightness(brightness)
                if effect is not None:
                    effect.set_brightness(brightness)
            return {"ok": True, "connected": True, "sequence": sequence}
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def set_timing(self, timing_ms: int | str) -> dict:
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            timing = max(1, min(0xFFFF, int(timing_ms)))
            sequence = self.controller.set_timing(timing)
            effect = getattr(self, "media_effect", None)
            if effect is not None and effect.status()["active"]:
                effect.set_duration(transition_duration_for_timing(timing))
            return {"ok": True, "connected": True, "sequence": sequence}
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def set_white_balance(self, red: int | str, green: int | str, blue: int | str) -> dict:
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            values = [max(0, min(255, int(value))) for value in (red, green, blue)]
            sequence = self.controller.set_white_balance(*values)
            return {
                "ok": True,
                "connected": True,
                "sequence": sequence,
                "whiteBalance": values,
            }
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def restart(self) -> dict:
        self._stop_media_effect()
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            sequence = self.controller.restart()
            self.controller.disconnect()
            return {"ok": True, "connected": False, "sequence": sequence, "restarting": True}
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def reset_state(self) -> dict:
        self._stop_media_effect()
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            sequence = self.controller.reset_state()
            self.controller.disconnect()
            return {"ok": True, "connected": False, "sequence": sequence, "restarting": True}
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def status(self) -> dict:
        return {"ok": True, "connected": self.controller.connected}

    def _snapshot_to_ui_state(self, snapshot) -> dict:
        mode = snapshot.mode
        brightness = round(snapshot.brightness_max * 100 / 255)
        speed = 50 if not snapshot.timing else max(10, min(200, round(1000 / snapshot.timing)))
        state = {
            "version": 1,
            "source": "quick",
            "mode": "静态常亮",
            "brightness": brightness,
            "speed": speed,
            "colors": [_rgb_hex(color) for color in snapshot.colors],
            "whiteBalance": list(snapshot.white_balance),
            "paintColor": "#8dc9bc",
            "matrix144x6": _blank_ui_matrix(),
        }

        if mode == 0:
            state["colors"] = ["#000000"]
            state["brightness"] = 0
        elif mode == 1:
            state["mode"] = "静态常亮"
            state["colors"] = state["colors"] or ["#000000"]
        elif mode == 2:
            state["mode"] = "呼吸渐变"
            state["colors"] = state["colors"] or ["#000000"]
        elif mode == 3:
            state["mode"] = "流光溢彩"
            state["speed"] = 50
            # Rainbow colors are generated by the firmware; retain the client's palette in the UI.
            state["colors"] = []
        elif mode == 4 and snapshot.matrix is not None:
            state["source"] = "matrix"
            state["mode"] = "自定义矩阵"
            state["matrix144x6"] = [
                [_rgb_hex(color) for color in row]
                for row in snapshot.matrix
            ]
        else:
            raise ValueError("board snapshot mode cannot be represented by the client")
        return state

    def sync(self) -> dict:
        try:
            if not self.controller.connected:
                return {"ok": False, "connected": False, "error": "无法同步：设备未连接"}
            snapshot = self.controller.sync()
            state = self._snapshot_to_ui_state(snapshot)
            effect = getattr(self, "media_effect", None)
            if effect is not None and effect.status()["active"]:
                state.update(mode=MEDIA_MODE, source="quick", colors=[])
            return {
                "ok": True,
                "connected": True,
                "state": state,
            }
        except (ControllerError, OSError, ValueError, TypeError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def load_state(self) -> dict:
        state = self.ui_state_store.load()
        return {"ok": True, "state": state}

    def save_state(self, state: dict) -> dict:
        try:
            normalized = normalize_ui_state(state)
            return {"ok": True, "state": self.ui_state_store.save(normalized)}
        except (OSError, TypeError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    def _apply_mode(self, settings: dict) -> int | None:
        colors = _settings_colors(settings)
        color = colors[0]
        brightness = _brightness(settings.get("brightness", 80))
        mode = settings.get("mode", "静态常亮")

        if mode == MEDIA_MODE:
            duration = transition_duration_for_speed(settings.get("speed", 50))
            self.media_effect.activate(color, brightness, duration)
            return None

        self._stop_media_effect()

        if mode == "静态常亮":
            return self.controller.fill(color, brightness)
        if mode == "自定义矩阵":
            return self._send_matrix(settings.get("matrix144x6", []), brightness)
        if mode == "呼吸渐变":
            return self.controller.breathe(colors, 0, brightness)
        if mode in ("流光溢彩", "彩虹跑马"):
            return self.controller.rainbow(
                brightness=brightness,
                interval=RAINBOW_FRAME_INTERVAL,
                duration=RAINBOW_FRAME_INTERVAL,
                pingpong=True,
            )
        raise ValueError(f"unsupported LED mode: {mode}")

    def apply(self, settings: dict) -> dict:
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            seq = self._apply_mode(settings)
            result = {"ok": True, "connected": True, "sequence": seq}
            if settings.get("mode") == MEDIA_MODE:
                result["media"] = self.media_effect.status()
            return result
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def set_power(self, enabled: bool, settings: dict | None = None) -> dict:
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            if not enabled:
                self._stop_media_effect()
                seq = self.controller.clear()
            else:
                seq = self._apply_mode(settings or {})
            return {"ok": True, "connected": True, "sequence": seq}
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def _send_matrix(self, matrix: list, brightness: int = 255) -> int:
        self._stop_media_effect()
        pixels = []
        for row, values in enumerate(matrix[:6]):
            for column, value in enumerate(values[:144]):
                red, green, blue = _hex_color(value)
                if (red, green, blue) != (0, 0, 0):
                    pixels.append((column, row, brightness, red, green, blue))
        self.controller.clear()
        if pixels:
            self.controller.set_pixels(pixels, coordinate_mode=True)
        return self.controller.show()

    def send_matrix(self, matrix: list, color: tuple[int, int, int] | None = None, brightness: int = 255) -> dict:
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            seq = self._send_matrix(matrix, brightness)
            return {"ok": True, "connected": True, "sequence": seq}
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

    def list_shapes(self) -> dict:
        return {"ok": True, "shapes": self.shape_store.list_shapes()}

    def save_shape(self, name: str, matrix: list) -> dict:
        try:
            shape = self.shape_store.save_user_shape(name, matrix)
            return {"ok": True, "shape": shape}
        except (OSError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    def update_shape(self, shape_id: str, name: str, matrix: list) -> dict:
        try:
            shape = self.shape_store.update_user_shape(shape_id, name, matrix)
            return {"ok": True, "shape": shape}
        except (OSError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    def delete_shape(self, shape_id: str) -> dict:
        try:
            self.shape_store.delete_user_shape(shape_id)
            return {"ok": True}
        except (OSError, ValueError) as error:
            return {"ok": False, "error": str(error)}

    def send_shape(self, shape_id: str, brightness: int = 255, paint_color: str = "#8dc9bc") -> dict:
        try:
            if not self.controller.connected and not self.controller.connect():
                return {"ok": False, "connected": False, "error": "无法连接 ESP32"}
            shape = self.shape_store.get_shape(shape_id)
            if shape is None:
                raise ValueError("shape does not exist")
            matrix = (
                materialize_preset(shape["matrix"], paint_color)
                if shape["kind"] == "preset"
                else shape["matrix"]
            )
            sequence = self._send_matrix(matrix, int(brightness))
            return {"ok": True, "connected": True, "sequence": sequence}
        except (ControllerError, OSError, ValueError) as error:
            return {"ok": False, "connected": self.controller.connected, "error": str(error)}

class WebviewWindow:
    def __init__(self, bridge: JavaScriptBridge) -> None:
        self.bridge = bridge
        loader = ConfigLoader("config.json")
        config = loader.read_config()
        self.config = config

        title = config["webview"]["window"]["title"]
        width = config["webview"]["window"]["width"]
        height = config["webview"]["window"]["height"]
        min_size = tuple(config["webview"]["window"]["min_size"])
        resizable = config["webview"]["window"]["resizable"]
        frameless = config["webview"]["window"]["frameless"]
        fullscreen = config["webview"]["window"]["fullscreen"]

        background = CLIENT_DIR / "webui" / "assets" / "background.png"
        self._blank_server = BlankPageServer(background)
        shell_url = self._blank_server.start()
        self._shell_url = shell_url
        bridge.set_ui_ready_callback(self._blank_server.stop)
        try:
            self.window = webview.create_window(
                title=title,
                url=shell_url,
                width=width,
                height=height,
                min_size=min_size,
                resizable=resizable,
                frameless=frameless,
                fullscreen=fullscreen,
                background_color="#000000",
                js_api=bridge,
            )
        except Exception:
            self._blank_server.stop()
            raise

        self._scripts_injected = False

    def _load_scripts(self) -> tuple[str, str, str]:
        script_dir = CLIENT_DIR / self.config["webview"]["script_dir"]
        with open(script_dir / "runtime_const.js", "r", encoding="utf-8") as f:
            constants = f.read()
        with open(script_dir / "index.js", "r", encoding="utf-8") as f:
            index = f.read()
        background = CLIENT_DIR / "webui" / "assets" / "background.png"
        background_url = f"{self._shell_url}background.png" if background.exists() else ""
        asset_context = f"window.__runtimeBackgroundUrl = {json.dumps(background_url)};"
        return asset_context, constants, index

    def _inject_scripts(self) -> None:
        if self._scripts_injected:
            return
        try:
            asset_context, constants, index = self._load_scripts()
            self.window.run_js(asset_context)
            self.window.run_js(constants)
            self.window.run_js(index)
            self._scripts_injected = True
        except Exception:
            # If the bootstrap itself fails, do not leave the temporary server
            # alive until the user closes the window.
            self._blank_server.stop()
            raise

    def run(self, debug: bool = False) -> None:
        self.window.events.loaded += self._inject_scripts
        try:
            webview.start(debug=debug)
        finally:
            # Also clean up when the window closes before ``loaded`` fires.
            self._blank_server.stop()
            self.bridge.close()
