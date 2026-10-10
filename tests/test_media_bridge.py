import asyncio
import threading
import unittest

from client.media_color import MEDIA_MODE, MediaColorEffect, MediaSnapshot
from client.sync_state import SyncSnapshot
from client.ui_state import normalize_ui_state
from client.webui.webui import JavaScriptBridge


class Controller:
    connected = True

    def __init__(self):
        self.calls = []

    def fill(self, color, brightness):
        self.calls.append(("fill", color, brightness))
        return 1

    def transition(self, target, duration):
        self.calls.append(("transition", target, duration))
        return 2

    def clear(self):
        self.calls.append(("clear",))
        return 3

    def show(self):
        self.calls.append(("show",))
        return 4

    def sync(self):
        return SyncSnapshot(1, 180, 180, 20, ((220, 40, 70),), None, (255, 190, 110))

    def connect(self):
        self.connected = True
        return True

    def health(self):
        self.connected = True
        return True

    def enter_maintenance(self):
        self.calls.append(("maintenance",))
        self.connected = False
        return 5


class Reader:
    async def read(self):
        return MediaSnapshot(False)


class MediaBridgeTests(unittest.IsolatedAsyncioTestCase):
    def make_bridge(self):
        bridge = JavaScriptBridge.__new__(JavaScriptBridge)
        bridge.controller = Controller()
        bridge.media_effect = MediaColorEffect(bridge.controller, reader=Reader(), autostart=False)
        return bridge

    async def test_media_mode_uses_first_default_color_and_transition(self):
        bridge = self.make_bridge()
        result = bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233", "#445566"], "brightness": 80})
        self.assertTrue(result["ok"])
        await bridge.media_effect.refresh()
        self.assertEqual(bridge.controller.calls, [("transition", (17, 34, 51, 204), 800)])

    def test_brightness_ack_cannot_be_overwritten_by_an_older_cover_read(self):
        bridge = self.make_bridge()
        bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233"], "brightness": 80})
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        async def delayed_read():
            entered.set()
            await asyncio.to_thread(release.wait, 2)
            return MediaSnapshot(False)

        bridge.media_effect.reader.read = delayed_read

        def refresh():
            try:
                asyncio.run(bridge.media_effect.refresh())
            finally:
                finished.set()

        def set_brightness(value):
            bridge.controller.calls.append(("brightness", value))
            release.set()
            # Simulate the ACK path being delayed while the old read finishes.
            finished.wait(0.2)
            return 6

        bridge.controller.set_brightness = set_brightness
        worker = threading.Thread(target=refresh)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertTrue(bridge.set_brightness(40)["ok"])
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(bridge.controller.calls, [("brightness", 102)])
            asyncio.run(bridge.media_effect.refresh())
            self.assertEqual(bridge.controller.calls[-1], ("transition", (17, 34, 51, 102), 800))
        finally:
            release.set()
            worker.join(timeout=2)
            bridge.media_effect.close()

    async def test_switching_to_static_or_matrix_stops_following(self):
        bridge = self.make_bridge()
        bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233"], "brightness": 80})
        bridge.apply({"mode": "静态常亮", "colors": ["#445566"], "brightness": 80})
        await bridge.media_effect.refresh()
        self.assertEqual(bridge.controller.calls, [("fill", (68, 85, 102), 204)])
        bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233"], "brightness": 80})
        bridge.send_matrix([["#000000"] * 144 for _ in range(6)])
        self.assertFalse(bridge.media_effect.status()["active"])

    async def test_sync_keeps_client_media_mode_and_does_not_replace_fallback_palette(self):
        bridge = self.make_bridge()
        bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233"], "brightness": 80})
        state = bridge.sync()["state"]
        self.assertEqual(state["mode"], MEDIA_MODE)
        self.assertEqual(state["colors"], [])
        self.assertEqual(state["whiteBalance"], [255, 190, 110])

    async def test_reconnect_waits_for_sync_and_adopted_brightness_before_output(self):
        bridge = self.make_bridge()
        bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233"], "brightness": 80})
        await bridge.media_effect.refresh()
        bridge.controller.calls.clear()
        bridge.controller.connected = False
        self.assertTrue(bridge.connect()["ok"])
        await bridge.media_effect.refresh()
        self.assertEqual(bridge.controller.calls, [])
        self.assertEqual(bridge.sync()["state"]["mode"], MEDIA_MODE)
        bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233"], "brightness": 20})
        await bridge.media_effect.refresh()
        self.assertEqual(bridge.controller.calls, [("transition", (17, 34, 51, 51), 800)])

    async def test_health_recovery_also_waits_for_sync(self):
        bridge = self.make_bridge()
        bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233"], "brightness": 80})
        bridge.controller.connected = False
        result = bridge.health()
        self.assertTrue(result.get("recovered"))
        await bridge.media_effect.refresh()
        self.assertEqual(bridge.controller.calls, [])

    async def test_maintenance_stops_media_polling_before_command(self):
        bridge = self.make_bridge()
        bridge.apply({"mode": MEDIA_MODE, "colors": ["#112233"], "brightness": 80})
        self.assertTrue(bridge.enter_maintenance()["ok"])
        await bridge.media_effect.refresh()
        self.assertEqual(bridge.controller.calls, [("maintenance",)])

    async def test_ui_state_can_remember_media_mode(self):
        state = normalize_ui_state({
            "version": 1, "source": "quick", "mode": MEDIA_MODE,
            "colors": ["#112233"], "paintColor": "#445566", "brightness": 80,
            "speed": 50, "matrix144x6": [["#000000"] * 144 for _ in range(6)],
        })
        self.assertEqual(state["mode"], MEDIA_MODE)
        self.assertEqual(state["colors"], ["#112233"])


if __name__ == "__main__":
    unittest.main()
