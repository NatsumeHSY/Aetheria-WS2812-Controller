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


def load_protocol_helpers():
    protocol = load_extracted_board_module("protocol")
    state = importlib.reload(load_extracted_board_module("state"))
    effects = load_extracted_board_module("effects")
    tree = ast.parse(BOARD_MAIN.read_text(encoding="utf-8"))
    wanted = {
        "_blank_matrix",
        "_copy_matrix",
        "_normalize_rgb",
        "_snapshot_write",
        "build_sync_response",
        "copy_light_snapshot",
        "next_sequence",
        "crc4_itu",
        "calculate_packet_crc",
        "validate_packet",
        "classify_sequence",
        "interpolate_color_state",
        "restore_health_session",
        "get_global_timing",
        "update_breathe_snapshot",
        "update_fill_snapshot",
        "update_matrix_snapshot",
        "update_rainbow_snapshot",
    }
    definitions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    namespace = {
        "SOCKET_MAGIC": b"LD",
        "PROTOCOL_HEADER_SIZE": 7,
        "PROTOCOL_TRAILER_SIZE": 1,
        "MAX_PACKET_SIZE": 6144,
        "HEALTH_COMMAND": b"\xF1",
        "SYNC_RESPONSE": b"\x04",
        "RESPONSE_SYNC": b"\x04",
        "SYNC_VERSION": 2,
        "LED_LINE": 6,
        "LED_DOT_PER_LINE": 144,
        "LED_COUNT": 864,
        "COLOR_BLACK": (0, 0, 0),
        "SNAPSHOT_LOCK": type("Lock", (), {
            "acquire": lambda self: None,
            "release": lambda self: None,
        })(),
        "LIGHT_SNAPSHOT": {
            "mode": 0,
            "brightness_min": 0,
            "brightness_max": 0,
            "timing": 0,
            "colors": [],
            "matrix": None,
        },
        "LIGHT_EFFECT_PARAMS": {},
        "GLOBAL_TIMING_MS": 0,
    }
    namespace.update({
        "next_sequence": protocol.next_sequence,
        "crc4_itu": protocol.crc4_itu,
        "calculate_packet_crc": protocol.calculate_packet_crc,
        "validate_packet": protocol.validate_packet,
        "classify_sequence": protocol.classify_sequence,
        "restore_health_session": protocol.restore_health_session,
        "interpolate_color_state": effects.interpolate_color_state,
    })
    for name in (
        "_blank_matrix",
        "_copy_matrix",
        "_normalize_rgb",
        "_snapshot_write",
        "copy_light_snapshot",
        "get_global_timing",
        "get_global_white_balance",
        "update_breathe_snapshot",
        "update_fill_snapshot",
        "update_matrix_snapshot",
        "update_rainbow_snapshot",
    ):
        namespace[name] = getattr(state, name)
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(BOARD_MAIN), "exec"), namespace)
    return namespace


def load_runtime_parameter_helpers():
    state = importlib.reload(load_extracted_board_module("state"))
    state.LIGHT_SNAPSHOT = {
        "mode": 1,
        "brightness_min": 80,
        "brightness_max": 80,
        "timing": 0,
        "colors": [[10, 20, 30]],
        "matrix": None,
    }
    state.GLOBAL_BRIGHTNESS = 255
    state.GLOBAL_TIMING_MS = 0
    tree = ast.parse(BOARD_MAIN.read_text(encoding="utf-8"))
    wanted = {
        "_copy_matrix",
        "_normalize_rgb",
        "_snapshot_write",
        "copy_light_snapshot",
        "get_global_brightness",
        "get_global_timing",
        "set_global_brightness",
        "set_global_timing",
        "redraw_static_snapshot",
        "update_fill_snapshot",
        "xy2pos",
    }
    definitions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]

    class FakeDriver:
        def __init__(self):
            self.fills = []
            self.pixels = []
            self.shows = 0
            self.clears = 0

        def fill(self, color, brightness):
            self.fills.append((tuple(color), brightness))

        def set_pixel(self, index, color, brightness, auto_write):
            self.pixels.append((index, tuple(color), brightness, auto_write))

        def show(self):
            self.shows += 1

        def clear(self):
            self.clears += 1

    namespace = {
        "LED_LINE": 6,
        "LED_DOT_PER_LINE": 144,
        "LED_MAX_BRIGHTNESS": 255,
        "GLOBAL_BRIGHTNESS": 255,
        "GLOBAL_TIMING_MS": 0,
        "SNAPSHOT_LOCK": type("Lock", (), {
            "acquire": lambda self: None,
            "release": lambda self: None,
        })(),
        "LIGHT_SNAPSHOT": {
            "mode": 1,
            "brightness_min": 80,
            "brightness_max": 80,
            "timing": 0,
            "colors": [[10, 20, 30]],
            "matrix": None,
        },
        "LIGHT_EFFECT_PARAMS": {},
        "DRIVER": FakeDriver(),
    }
    for name in (
        "_copy_matrix",
        "_normalize_rgb",
        "_snapshot_write",
        "copy_light_snapshot",
        "get_global_brightness",
        "get_global_timing",
        "set_global_brightness",
        "set_global_timing",
        "update_fill_snapshot",
    ):
        namespace[name] = getattr(state, name)
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(BOARD_MAIN), "exec"), namespace)
    return namespace


class BoardProtocolTests(unittest.TestCase):
    def test_board_exposes_white_balance_parameter_handler(self):
        source = BOARD_MAIN.read_text(encoding="utf-8")

        self.assertIn("def led_set_white_balance(length: int, payload: list)", source)
        self.assertIn("if length != 3:", source)
        self.assertIn("PARAM_WHITE_BALANCE_COMMAND: led_set_white_balance", source)

    def test_extracted_protocol_module_exports_a2_and_sequence_helpers(self):
        config = load_extracted_board_module("config")
        protocol = load_extracted_board_module("protocol")

        self.assertEqual(config.PARAM_WHITE_BALANCE_COMMAND, b"\xA2")
        self.assertEqual(protocol.next_sequence(0xFFFF), 0)
        self.assertEqual(
            protocol.calculate_packet_crc(0x12, [0x10, 0x20]),
            protocol.crc4_itu(0x12 ^ 0x10 ^ 0x20),
        )

    def test_audio_response_is_not_registered_in_board_runtime(self):
        config = load_extracted_board_module("config")
        source = BOARD_MAIN.read_text(encoding="utf-8")

        self.assertFalse(hasattr(config, "AUDIO_COMMAND"))
        self.assertNotIn("AUDIO_COMMAND: led_audio_control", source)
        self.assertNotIn("accept_audio_frame", source)

    def test_validate_packet_requires_exact_header_and_payload_length(self):
        validate_packet = load_protocol_helpers()["validate_packet"]

        self.assertEqual(validate_packet(b"LD\x01\x00\x00\x00\x01\x03"), (True, b"\x01", 1, []))
        self.assertEqual(
            validate_packet(b"LD\x01\x00\x02\x00\x12\x10\x20\x0C"),
            (True, b"\x01", 0x12, [0x10, 0x20]),
        )
        self.assertEqual(validate_packet(b"LD"), (False, None, None, None))
        self.assertEqual(validate_packet(b"XX\x01\x00\x00\x00\x01\x03"), (False, None, None, None))
        self.assertEqual(validate_packet(b"LD\x01\x00\x02\x00\x01\xAA\x03"), (False, None, None, None))
        self.assertEqual(validate_packet(b"LD\x01\x00\x00\x00\x01"), (False, None, None, None))
        self.assertEqual(validate_packet(b"LD\x01\x00\x00\x00\x01\x04"), (False, None, None, None))
        self.assertEqual(validate_packet(b"LD\x01\x00\x00\x00\x01\xF3"), (False, None, None, None))

    def test_crc4_itu_uses_the_xor_byte(self):
        helpers = load_protocol_helpers()
        crc4_itu = helpers["crc4_itu"]
        calculate_packet_crc = helpers["calculate_packet_crc"]

        self.assertEqual(crc4_itu(0x00), 0x0)
        self.assertEqual(crc4_itu(0x01), 0x3)
        self.assertEqual(crc4_itu(0xA5), 0xB)
        self.assertEqual(calculate_packet_crc(0x12, [0x10, 0x20]), crc4_itu(0x12 ^ 0x10 ^ 0x20))

    def test_sequence_wraps_after_ffff(self):
        next_sequence = load_protocol_helpers()["next_sequence"]

        self.assertEqual(next_sequence(0x0000), 0x0001)
        self.assertEqual(next_sequence(0xFFFE), 0xFFFF)
        self.assertEqual(next_sequence(0xFFFF), 0x0000)

    def test_sequence_classifier_accepts_ordered_packets_and_rejects_replay_or_gap(self):
        classify_sequence = load_protocol_helpers()["classify_sequence"]

        self.assertEqual(classify_sequence(None, 0x1234), ("accept", 0x1235))
        self.assertEqual(classify_sequence(0x1235, 0x1235), ("accept", 0x1236))
        self.assertEqual(classify_sequence(0x1235, 0x1234), ("replay", 0x1235))
        self.assertEqual(classify_sequence(0x1235, 0x1237), ("gap", 0x1235))
        self.assertEqual(classify_sequence(0x0000, 0x0000), ("accept", 0x0001))

    def test_color_transition_interpolates_rgb_and_brightness(self):
        interpolate = load_protocol_helpers()["interpolate_color_state"]

        self.assertEqual(
            interpolate((10, 20, 30, 40), (110, 220, 130, 200), 0, 10),
            (10, 20, 30, 40),
        )
        self.assertEqual(
            interpolate((10, 20, 30, 40), (110, 220, 130, 200), 5, 10),
            (60, 120, 80, 120),
        )
        self.assertEqual(
            interpolate((10, 20, 30, 40), (110, 220, 130, 200), 10, 10),
            (110, 220, 130, 200),
        )

    def test_board_exposes_color_transition_command(self):
        source = BOARD_MAIN.read_text(encoding="utf-8")

        self.assertIn("def led_transition(length: int, payload: list)", source)
        self.assertIn("if length != 6: return", source)
        self.assertIn('b"\\x09": led_transition', source)

    def test_health_replaces_port_for_the_same_client_ip_without_advancing_sequence(self):
        restore = load_protocol_helpers()["restore_health_session"]

        accepted, address, expected = restore(
            ("192.168.4.2", 4000),
            ("192.168.4.2", 5000),
            0x1234,
        )

        self.assertTrue(accepted)
        self.assertEqual(address, ("192.168.4.2", 5000))
        self.assertEqual(expected, 0x1234)

    def test_health_uses_zero_when_session_has_not_sent_a_command(self):
        restore = load_protocol_helpers()["restore_health_session"]

        self.assertEqual(
            restore(("192.168.4.2", 4000), ("192.168.4.2", 5000), None),
            (True, ("192.168.4.2", 5000), 0),
        )

    def test_health_rejects_unknown_client_ip_without_changing_session(self):
        restore = load_protocol_helpers()["restore_health_session"]

        self.assertEqual(
            restore(("192.168.4.2", 4000), ("192.168.4.9", 5000), 0x1234),
            (False, ("192.168.4.2", 4000), 0x1234),
        )

    def test_snapshot_starts_off_and_records_supported_effects(self):
        helpers = load_protocol_helpers()
        copy_snapshot = helpers["copy_light_snapshot"]

        self.assertEqual(copy_snapshot()["mode"], 0)
        self.assertIsNone(copy_snapshot()["matrix"])

        helpers["update_fill_snapshot"]((1, 2, 3), 77)
        self.assertEqual(
            copy_snapshot(),
            {
                "mode": 1,
                "brightness_min": 77,
                "brightness_max": 77,
                "timing": 0,
                "colors": [[1, 2, 3]],
                "matrix": None,
            },
        )

        helpers["update_breathe_snapshot"]([(10, 20, 30), (40, 50, 60)], 5, 200)
        self.assertEqual(copy_snapshot()["mode"], 2)
        self.assertEqual(copy_snapshot()["colors"], [[10, 20, 30], [40, 50, 60]])
        self.assertEqual((copy_snapshot()["brightness_min"], copy_snapshot()["brightness_max"]), (5, 200))

        helpers["update_rainbow_snapshot"](123, 456)
        self.assertEqual(copy_snapshot()["mode"], 3)
        self.assertEqual(copy_snapshot()["timing"], 456)
        self.assertEqual(copy_snapshot()["colors"], [])

    def test_snapshot_records_full_matrix_and_builds_bounded_crc_response(self):
        helpers = load_protocol_helpers()
        matrix = [
            [[(row + column) & 0xFF, (column * 2) & 0xFF, row] for column in range(144)]
            for row in range(6)
        ]
        helpers["update_matrix_snapshot"](matrix, 180)

        snapshot = helpers["copy_light_snapshot"]()
        self.assertEqual(snapshot["mode"], 4)
        self.assertEqual(snapshot["matrix"][0][0], [0, 0, 0])
        self.assertEqual(snapshot["matrix"][5][143], [148 & 0xFF, 286 & 0xFF, 5])

        response = helpers["build_sync_response"](0xBEEF)
        self.assertLess(len(response), 6144)
        valid, command, seq, payload = helpers["validate_packet"](response)
        self.assertTrue(valid)
        self.assertEqual(command, b"\x04")
        self.assertEqual(seq, 0xBEEF)
        self.assertEqual(payload[0], 2)
        self.assertEqual(payload[1], 4)
        self.assertEqual(tuple(payload[6:9]), (255, 255, 255))
        self.assertEqual(len(payload), 11 + 864 * 3)

    def test_sync_session_restores_same_ip_without_advancing_expected_sequence(self):
        restore = load_protocol_helpers()["restore_health_session"]

        self.assertEqual(
            restore(("192.168.4.2", 4000), ("192.168.4.2", 5000), 0x1234),
            (True, ("192.168.4.2", 5000), 0x1234),
        )
        self.assertEqual(
            restore(("192.168.4.2", 4000), ("192.168.4.9", 5000), 0x1234),
            (False, ("192.168.4.2", 4000), 0x1234),
        )

    def test_global_brightness_redraws_static_output_without_clearing(self):
        helpers = load_runtime_parameter_helpers()

        helpers["set_global_brightness"](120)
        helpers["redraw_static_snapshot"]()

        self.assertEqual(helpers["copy_light_snapshot"]()["brightness_max"], 120)
        self.assertEqual(helpers["DRIVER"].fills, [((10, 20, 30), 120)])
        self.assertEqual(helpers["DRIVER"].clears, 0)

    def test_global_timing_updates_sync_snapshot_without_touching_led_output(self):
        helpers = load_runtime_parameter_helpers()

        helpers["set_global_timing"](33)

        self.assertEqual(helpers["copy_light_snapshot"]()["timing"], 33)
        self.assertEqual(helpers["DRIVER"].fills, [])


if __name__ == "__main__":
    unittest.main()
