import importlib
import sys
import unittest
from pathlib import Path


BOARD_DIR = Path(__file__).parents[1] / "board"


def load_driver_module():
    board_path = str(BOARD_DIR)
    if board_path not in sys.path:
        sys.path.insert(0, board_path)
    return importlib.import_module("led_driver")


class BoardWhiteBalanceTests(unittest.TestCase):
    def test_default_white_balance_preserves_rgb(self):
        driver = load_driver_module()

        self.assertEqual(
            driver.apply_white_balance((100, 150, 200), (255, 255, 255)),
            (100, 150, 200),
        )

    def test_white_balance_scales_each_channel_independently(self):
        driver = load_driver_module()

        self.assertEqual(
            driver.apply_white_balance((200, 200, 200), (255, 128, 64)),
            (200, 100, 50),
        )

    def test_white_balance_then_brightness_matches_driver_output(self):
        driver = load_driver_module()

        corrected = driver.apply_white_balance((255, 200, 100), (255, 192, 128))
        output = driver.scale_with_brightness(corrected, 128)

        self.assertEqual(output, (128, 75, 25))


if __name__ == "__main__":
    unittest.main()
