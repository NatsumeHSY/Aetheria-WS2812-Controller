import unittest
from pathlib import Path

import client.protocol as protocol
from client.controller import LEDController
from client.webui.webui import JavaScriptBridge


ROOT = Path(__file__).resolve().parents[1]


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeMaintenanceController:
    def __init__(self):
        self.connected = True
        self.calls = []

    def enter_maintenance(self):
        self.calls.append(("enter_maintenance",))
        self.connected = False
        return 7


class FakeControlController:
    def __init__(self):
        self.connected = True
        self.calls = []

    def set_brightness(self, value):
        self.calls.append(("set_brightness", value))
        return 1

    def set_timing(self, value):
        self.calls.append(("set_timing", value))
        return 2

    def restart(self):
        self.calls.append(("restart",))
        return 3

    def reset_state(self):
        self.calls.append(("reset_state",))
        return 4

    def disconnect(self):
        self.calls.append(("disconnect",))
        self.connected = False


class ClientMaintenanceTests(unittest.TestCase):
    def test_protocol_exposes_f3_maintenance_packet(self):
        command = getattr(protocol, "MAINTENANCE_COMMAND", None)
        builder = getattr(protocol, "build_maintenance_packet", None)
        self.assertIsNotNone(command, "client protocol must expose maintenance command")
        self.assertIsNotNone(builder, "client protocol must build maintenance packets")
        if command is None or builder is None:
            return

        packet = builder(0x002A)

        self.assertEqual(packet[:7], b"LD\xF3\x00\x00\x00\x2A")
        self.assertEqual(protocol.decode_packet(packet), (command, 0x002A, []))

    def test_controller_enters_maintenance_and_closes_owned_socket_after_ack(self):
        controller = LEDController.__new__(LEDController)
        controller.connected = True
        controller._history = {7: b"packet"}
        controller._owns_socket = True
        controller._socket = FakeSocket()
        socket = controller._socket
        calls = []

        def send_packet(command, payload):
            calls.append((command, bytes(payload)))
            return 7

        controller._send_packet = send_packet
        enter = getattr(controller, "enter_maintenance", None)
        self.assertIsNotNone(enter, "controller must expose maintenance entry")
        if enter is None:
            return

        self.assertEqual(enter(), 7)

        self.assertEqual(calls, [(0xF3, b"")])
        self.assertFalse(controller.connected)
        self.assertEqual(controller._history, {})
        self.assertTrue(socket.closed)
        self.assertIsNone(controller._socket)

    def test_bridge_exposes_maintenance_result(self):
        bridge = JavaScriptBridge.__new__(JavaScriptBridge)
        bridge.controller = FakeMaintenanceController()
        enter = getattr(bridge, "enter_maintenance", None)
        self.assertIsNotNone(enter, "bridge must expose maintenance entry")
        if enter is None:
            return

        self.assertEqual(
            enter(),
            {
                "ok": True,
                "connected": False,
                "maintenance": True,
                "sequence": 7,
            },
        )
        self.assertEqual(bridge.controller.calls, [("enter_maintenance",)])

    def test_ui_exposes_consistent_maintenance_action_and_stops_health_polling(self):
        template = (ROOT / "client" / "webui" / "templates" / "index.html").read_text(encoding="utf-8")
        runtime_constants = (ROOT / "client" / "webui" / "scripts" / "runtime_const.js").read_text(encoding="utf-8")
        runtime_index = (ROOT / "client" / "webui" / "scripts" / "index.js").read_text(encoding="utf-8")

        for source in (template, runtime_constants):
            self.assertIn('id="maintenanceButton"', source)
            self.assertIn("进入维护模式", source)
            self.assertIn("maintenance-button", source)
            self.assertIn('class="tool-button maintenance-button"', source)
            self.assertIn(".maintenance-button.tool-button { min-height: 0; padding: 9px 13px; color: var(--ink-muted);", source)
            self.assertIn(".maintenance-button.tool-button:hover", source)
            self.assertIn(".maintenance-button.tool-button:hover { color: var(--coral);", source)
            self.assertIn(".maintenance-button.tool-button:active", source)
            self.assertIn('id="restartButton"', source)
            self.assertIn('id="resetStateButton"', source)
            self.assertIn("重启设备", source)
            self.assertIn("重置设备", source)
            self.assertIn('class="tool-button" id="restartButton"', source)
            self.assertIn('class="tool-button" id="resetStateButton"', source)
            self.assertNotIn('class="device-action"', source)
            self.assertNotIn(".device-action:hover", source)
            self.assertNotIn(".device-action:active", source)

        self.assertIn("function enterMaintenanceMode", runtime_index)
        self.assertIn('bridgeCall("enter_maintenance")', runtime_index)
        self.assertIn('sendDeviceLifecycleCommand("restart"', runtime_index)
        self.assertIn('sendDeviceLifecycleCommand("reset_state"', runtime_index)
        self.assertIn("板端保存的状态将被删除并重启设备", runtime_index)
        self.assertIn("maintenanceMode", runtime_index)
        self.assertIn("clearInterval(healthTimer)", runtime_index)

    def test_bridge_exposes_parameter_and_reset_controls(self):
        bridge = JavaScriptBridge.__new__(JavaScriptBridge)
        bridge.controller = FakeControlController()

        self.assertEqual(bridge.set_brightness(50), {"ok": True, "connected": True, "sequence": 1})
        self.assertEqual(bridge.set_timing(33), {"ok": True, "connected": True, "sequence": 2})
        self.assertEqual(bridge.restart(), {"ok": True, "connected": False, "sequence": 3, "restarting": True})

        bridge.controller.connected = True
        self.assertEqual(bridge.reset_state(), {"ok": True, "connected": False, "sequence": 4, "restarting": True})
        self.assertEqual(
            bridge.controller.calls,
            [
                ("set_brightness", 128),
                ("set_timing", 33),
                ("restart",),
                ("disconnect",),
                ("reset_state",),
                ("disconnect",),
            ],
        )


if __name__ == "__main__":
    unittest.main()
