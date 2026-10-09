import ast
import importlib
import sys
import unittest
from pathlib import Path


BOARD_MAIN = Path(__file__).parents[1] / "board" / "main.py"
BOARD_DIR = BOARD_MAIN.parent


def load_extracted_board_module(name):
    board_path = str(BOARD_DIR)
    if board_path not in sys.path:
        sys.path.insert(0, board_path)
    return importlib.import_module(name)


def load_persistence_helpers():
    module = load_extracted_board_module("persistence")
    return {
        name: getattr(module, name)
        for name in (
            "persistence_checksum",
            "encode_persisted_state",
            "decode_persisted_state",
            "atomic_write_persisted_state",
        )
    }


def load_restore_helper(state, driver, effector):
    runtime_state = importlib.reload(load_extracted_board_module("state"))
    effects = load_extracted_board_module("effects")
    tree = ast.parse(BOARD_MAIN.read_text(encoding="utf-8"))
    wanted = {
        "_blank_matrix",
        "_copy_matrix",
        "_normalize_rgb",
        "_snapshot_write",
        "copy_light_snapshot",
        "reset_light_snapshot",
        "update_fill_snapshot",
        "update_breathe_snapshot",
        "update_matrix_snapshot",
        "update_rainbow_snapshot",
        "get_global_timing",
        "get_global_brightness",
        "initialize_runtime_params",
        "restore_persisted_state",
        "xy2pos",
    }
    definitions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    namespace = {
        "LED_LINE": 6,
        "LED_DOT_PER_LINE": 144,
        "LED_COUNT": 864,
        "LED_MAX_BRIGHTNESS": 255,
        "LIGHT_SNAPSHOT": {
            "mode": 0,
            "brightness_min": 0,
            "brightness_max": 0,
            "timing": 0,
            "colors": [],
            "matrix": None,
        },
        "LIGHT_EFFECT_PARAMS": {},
        "GLOBAL_BRIGHTNESS": 255,
        "GLOBAL_TIMING_MS": 0,
        "SNAPSHOT_LOCK": type("Lock", (), {
            "acquire": lambda self: None,
            "release": lambda self: None,
        })(),
        "DRIVER": driver,
        "EFFECTOR": effector,
        "load_persisted_state": lambda: state,
    }
    for name in (
        "_blank_matrix",
        "_copy_matrix",
        "_normalize_rgb",
        "_snapshot_write",
        "copy_light_snapshot",
        "reset_light_snapshot",
        "update_fill_snapshot",
        "update_breathe_snapshot",
        "update_matrix_snapshot",
        "update_rainbow_snapshot",
        "get_global_timing",
        "get_global_brightness",
        "initialize_runtime_params",
    ):
        namespace[name] = getattr(runtime_state, name)
    namespace["xy2pos"] = effects.xy2pos
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(BOARD_MAIN), "exec"), namespace)
    return namespace


class BoardPersistenceTests(unittest.TestCase):
    def test_extracted_state_supports_atomic_white_balance_updates(self):
        state = load_extracted_board_module("state")
        state.set_global_white_balance(255, 190, 110)

        self.assertEqual(state.get_global_white_balance(), (255, 190, 110))
        state.set_global_white_balance(255, 255, 255)

    def test_static_and_rainbow_state_round_trip(self):
        helpers = load_persistence_helpers()
        snapshot = {
            "mode": 3,
            "brightness_min": 18,
            "brightness_max": 180,
            "timing": 0x1234,
            "colors": [],
            "matrix": None,
        }
        params = {
            "start_x": 7,
            "end_x": 131,
            "duration": 9,
            "pingpong": True,
        }

        encoded = helpers["encode_persisted_state"](snapshot, params)
        decoded = helpers["decode_persisted_state"](encoded)

        self.assertEqual(decoded["snapshot"], snapshot)
        self.assertEqual(decoded["effect_params"], params)

    def test_legacy_persistence_defaults_white_balance(self):
        helpers = load_persistence_helpers()
        snapshot = {
            "mode": 1,
            "brightness_min": 18,
            "brightness_max": 180,
            "timing": 0x1234,
            "colors": [[1, 2, 3]],
            "matrix": None,
        }
        encoded = helpers["encode_persisted_state"](
            snapshot,
            white_balance=(255, 190, 110),
        )
        legacy_without_checksum = encoded[:2] + b"\x01" + encoded[3:8] + encoded[11:-2]
        legacy = legacy_without_checksum + helpers["persistence_checksum"](legacy_without_checksum).to_bytes(2, "big")

        decoded = helpers["decode_persisted_state"](legacy)

        self.assertEqual(decoded["white_balance"], (255, 255, 255))

    def test_matrix_state_round_trip_preserves_all_black_pixels(self):
        helpers = load_persistence_helpers()
        matrix = [
            [[0, 0, 0] for _ in range(144)]
            for _ in range(6)
        ]
        matrix[0][0] = [12, 34, 56]
        snapshot = {
            "mode": 4,
            "brightness_min": 77,
            "brightness_max": 77,
            "timing": 0,
            "colors": [],
            "matrix": matrix,
        }

        decoded = helpers["decode_persisted_state"](
            helpers["encode_persisted_state"](snapshot)
        )

        self.assertEqual(decoded["snapshot"], snapshot)
        self.assertEqual(decoded["effect_params"], {})

    def test_corrupt_truncated_or_wrong_version_state_is_rejected(self):
        helpers = load_persistence_helpers()
        snapshot = {
            "mode": 1,
            "brightness_min": 10,
            "brightness_max": 10,
            "timing": 0,
            "colors": [[1, 2, 3]],
            "matrix": None,
        }
        encoded = helpers["encode_persisted_state"](snapshot)

        corrupt = bytearray(encoded)
        corrupt[6] ^= 0x01
        wrong_version = bytearray(encoded)
        wrong_version[2] = 0x7F

        self.assertIsNone(helpers["decode_persisted_state"](bytes(corrupt)))
        self.assertIsNone(helpers["decode_persisted_state"](encoded[:-1]))
        self.assertIsNone(helpers["decode_persisted_state"](bytes(wrong_version)))
        self.assertIsNone(helpers["decode_persisted_state"](encoded + b"\x00"))

    def test_atomic_state_write_uses_temp_file_and_replace(self):
        helpers = load_persistence_helpers()

        class FakeFile:
            def __init__(self):
                self.data = bytearray()
                self.flushed = False

            def write(self, data):
                self.data.extend(data)

            def flush(self):
                self.flushed = True

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeFilesystem:
            def __init__(self):
                self.calls = []

            def replace(self, source, target):
                self.calls.append((source, target))

        fake_file = FakeFile()
        fake_filesystem = FakeFilesystem()

        def opener(path, mode):
            self.assertEqual((path, mode), ("state.tmp", "wb"))
            return fake_file

        helpers["atomic_write_persisted_state"](
            b"state",
            "state.bin",
            "state.tmp",
            opener,
            fake_filesystem,
        )

        self.assertEqual(bytes(fake_file.data), b"state")
        self.assertTrue(fake_file.flushed)
        self.assertEqual(fake_filesystem.calls, [("state.tmp", "state.bin")])

    def test_restore_replays_saved_static_state_without_client(self):
        class FakeDriver:
            def __init__(self):
                self.fills = []

            def fill(self, color, brightness):
                self.fills.append((color, brightness))

        class FakeEffector:
            def __init__(self):
                self.stopped = []

            def stop(self, clear=True):
                self.stopped.append(clear)

        driver = FakeDriver()
        effector = FakeEffector()
        state = {
            "snapshot": {
                "mode": 1,
                "brightness_min": 90,
                "brightness_max": 90,
                "timing": 0,
                "colors": [[12, 34, 56]],
                "matrix": None,
            },
            "effect_params": {},
        }

        restored = load_restore_helper(state, driver, effector)["restore_persisted_state"]()

        self.assertTrue(restored)
        self.assertEqual(driver.fills, [((12, 34, 56), 90)])

    def test_restore_replays_saved_matrix_in_logical_coordinates(self):
        class FakeDriver:
            def __init__(self):
                self.pixels = []
                self.shows = 0

            def set_pixel(self, index, color, brightness, auto_write):
                self.pixels.append((index, color, brightness, auto_write))

            def show(self):
                self.shows += 1

        class FakeEffector:
            def stop(self, clear=True):
                self.clear = clear

        matrix = [
            [[0, 0, 0] for _ in range(144)]
            for _ in range(6)
        ]
        matrix[0][0] = [1, 2, 3]
        state = {
            "snapshot": {
                "mode": 4,
                "brightness_min": 77,
                "brightness_max": 77,
                "timing": 0,
                "colors": [],
                "matrix": matrix,
            },
            "effect_params": {},
        }
        driver = FakeDriver()

        restored = load_restore_helper(state, driver, FakeEffector())["restore_persisted_state"]()

        self.assertTrue(restored)
        self.assertEqual(len(driver.pixels), 6 * 144)
        self.assertEqual(driver.pixels[0], (0, (1, 2, 3), 77, False))
        self.assertEqual(driver.shows, 1)


if __name__ == "__main__":
    unittest.main()
