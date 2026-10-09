import unittest
from pathlib import Path


BOARD_MAIN = Path(__file__).parents[1] / "board" / "main.py"
BOARD_BOOT = Path(__file__).parents[1] / "board" / "boot.py"


class BoardStartupTests(unittest.TestCase):
    def test_boot_starts_access_point_before_main_is_loaded(self):
        self.assertTrue(BOARD_BOOT.exists(), "board/boot.py must be uploaded before main.py")
        source = BOARD_BOOT.read_text(encoding="utf-8")

        self.assertLess(source.index("network.WLAN(network.AP_IF)"), source.index("ap.active(True)"))
        self.assertLess(source.index("ap.active(True)"), source.index("ap.config("))
        self.assertNotIn("import socket", source)
        self.assertNotIn("import _thread", source)
        self.assertNotIn("from neopixel", source)

    def test_main_does_not_reinitialize_access_point(self):
        source = BOARD_MAIN.read_text(encoding="utf-8")
        setup_source = source[source.index("def setup()") : source.index("def loop()")]

        self.assertNotIn("start_ap(", setup_source)
        self.assertLess(setup_source.index("start_socket()"), setup_source.index("DRIVER = LedDriver()"))

    def test_waiting_animation_uses_rainbow_scan_without_fixed_color(self):
        source = BOARD_MAIN.read_text(encoding="utf-8")

        self.assertIn("EFFECTOR.scan_line_x(pingpong=True, rainbow=True)", source)
        self.assertNotIn("EFFECTOR.scan_line_x(color=COLOR_PINK, pingpong=True)", source)


if __name__ == "__main__":
    unittest.main()
