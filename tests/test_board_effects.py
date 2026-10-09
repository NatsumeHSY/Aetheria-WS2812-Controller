import ast
import importlib
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path


BOARD_MAIN = Path(__file__).parents[1] / "board" / "main.py"
BOARD_DIR = BOARD_MAIN.parent


def load_extracted_effects_module():
    board_path = str(BOARD_DIR)
    if board_path not in sys.path:
        sys.path.insert(0, board_path)
    return importlib.import_module("effects")


class StopFrame(Exception):
    pass


class FakeThread:
    def __init__(self):
        self.targets = []

    def start_new_thread(self, target, args):
        self.targets.append((target, args))
        return len(self.targets)


class FakeLock:
    def acquire(self):
        return True

    def release(self):
        return None


class FakeTime:
    def sleep_ms(self, value):
        if value == 100:
            return
        raise StopFrame(value)


class FakeDriver:
    def __init__(self):
        self.writes = []
        self.shows = 0
        self.clears = 0

    def set_pixel(self, index, color, brightness=255, auto_write=False):
        self.writes.append((index, tuple(color), brightness, auto_write))

    def show(self):
        self.shows += 1

    def clear(self):
        self.clears += 1


def load_effector():
    effects = importlib.reload(load_extracted_effects_module())
    state = importlib.import_module("state")
    state.GLOBAL_BRIGHTNESS = 255
    state.GLOBAL_TIMING_MS = 0

    thread = FakeThread()
    effects._thread = SimpleNamespace(
        start_new_thread=thread.start_new_thread,
        allocate_lock=lambda: FakeLock(),
    )
    effects.time = FakeTime()
    effects.math = __import__("math")
    driver = FakeDriver()
    namespace = {
        "rainbow_color": effects.rainbow_color,
        "xy2pos": effects.xy2pos,
    }
    return effects.Effector(driver), driver, thread, namespace


class BoardEffectTests(unittest.TestCase):
    def test_extracted_effects_module_exports_effector_and_utilities(self):
        effects = load_extracted_effects_module()

        self.assertTrue(hasattr(effects, "Effector"))
        self.assertEqual(effects.xy2pos(0, 1), 287)
        self.assertEqual(effects.rainbow_color(0), (0, 255, 0))

    def test_scan_line_without_rainbow_uses_supplied_color(self):
        effector, driver, threads, _ = load_effector()

        effector.scan_line_x(
            color=(11, 22, 33),
            start_x=0,
            end_x=0,
            brightness=200,
            duration=1,
            rainbow=False,
        )
        target, args = threads.targets[-1]

        with self.assertRaises(StopFrame):
            target(*args)

        self.assertEqual(len(driver.writes), 6)
        self.assertTrue(all(write[1] == (11, 22, 33) for write in driver.writes))

    def test_scan_line_with_rainbow_ignores_supplied_color(self):
        effector, driver, threads, namespace = load_effector()

        effector.scan_line_x(
            color=(11, 22, 33),
            start_x=0,
            end_x=0,
            brightness=200,
            duration=1,
            rainbow=True,
        )
        target, args = threads.targets[-1]

        with self.assertRaises(StopFrame):
            target(*args)

        expected = namespace["rainbow_color"](0)
        self.assertEqual(len(driver.writes), 6)
        self.assertTrue(all(write[1] == expected for write in driver.writes))

    def test_rainbow_writes_every_led_in_the_range_with_a_gradient(self):
        effector, driver, threads, _ = load_effector()

        effector.rainbow(start_x=0, end_x=2, brightness=200, duration=1)
        target, args = threads.targets[-1]

        with self.assertRaises(StopFrame):
            target(*args)

        self.assertEqual(len(driver.writes), 3 * 6)
        self.assertEqual(len({write[0] for write in driver.writes}), 3 * 6)
        self.assertGreater(len({write[1] for write in driver.writes}), 1)

    def test_stopped_effect_cannot_write_after_a_new_effect_starts(self):
        effector, driver, threads, _ = load_effector()

        effector.scan_line_x(color=(1, 2, 3), start_x=0, end_x=0, duration=1)
        old_target, old_args = threads.targets[-1]
        effector.stop(clear=False)
        effector.scan_line_x(color=(4, 5, 6), start_x=1, end_x=1, duration=1)

        driver.writes.clear()
        try:
            old_target(*old_args)
        except StopFrame:
            pass

        self.assertEqual(driver.writes, [])


if __name__ == "__main__":
    unittest.main()
