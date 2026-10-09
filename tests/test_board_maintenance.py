import ast
import unittest
from types import SimpleNamespace
from pathlib import Path
import sys


BOARD_MAIN = Path(__file__).parents[1] / "board" / "main.py"
BOARD_DIR = BOARD_MAIN.parent
if str(BOARD_DIR) not in sys.path:
    sys.path.insert(0, str(BOARD_DIR))

from protocol import classify_sequence


def load_maintenance_helpers():
    tree = ast.parse(BOARD_MAIN.read_text(encoding="utf-8"))
    wanted = {
        "next_sequence",
        "classify_sequence",
        "send_sequence_response",
        "process_maintenance_command",
        "process_restart_command",
        "process_reset_state_command",
        "clear_persisted_state",
        "_stop_before_reset",
        "enter_maintenance_mode",
        "exec_socket_buffer",
    }
    definitions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]

    class FakeSocket:
        def __init__(self):
            self.sent = []
            self.closed = False

        def sendto(self, data, address):
            self.sent.append((data, address))

        def close(self):
            self.closed = True

    class FakeEffecter:
        def __init__(self):
            self.stop_calls = []

        def stop(self, clear=True):
            self.stop_calls.append(clear)

    class FakeDriver:
        def __init__(self):
            self.clear_calls = 0

        def clear(self):
            self.clear_calls += 1

    class FakeTime:
        def __init__(self):
            self.sleeps = []

        def sleep_ms(self, value):
            self.sleeps.append(value)

    class FakeMachine:
        def __init__(self):
            self.reset_calls = 0

        def reset(self):
            self.reset_calls += 1

    class FakeFilesystem:
        def __init__(self, exists=True, remove_error=None):
            self.exists = exists
            self.remove_error = remove_error
            self.removed = []

        def stat(self, path):
            if not self.exists:
                raise OSError(2)
            return (path,)

        def remove(self, path):
            if self.remove_error is not None:
                raise self.remove_error
            self.removed.append(path)

    namespace = {
        "SOCKET_MAGIC": b"LD",
        "RESPONSE_ACK": b"\x01",
        "RESPONSE_RESEND": b"\x02",
        "SOCKET": FakeSocket(),
        "SOCKET_BUFFER": [(b"\x01", 4, [1, 2, 3, 4])],
        "CLIENT_ADDR": ("192.168.4.2", 7807),
        "EXPECTED_SEQ": 10,
        "MAINTENANCE_MODE": False,
        "EFFECTOR": FakeEffecter(),
        "DRIVER": FakeDriver(),
        "time": FakeTime(),
        "machine": FakeMachine(),
        "os": FakeFilesystem(),
        "PERSISTENCE_PATH": "state.bin",
        "classify_sequence": classify_sequence,
    }
    for handler_name in (
        "led_clear",
        "led_fill",
        "led_blink",
        "led_fade",
        "led_breathe",
        "led_rainbow",
        "led_transition",
        "led_floor_tile_x",
        "led_set_pixel",
        "led_show",
    ):
        namespace[handler_name] = lambda *args: None
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(BOARD_MAIN), "exec"), namespace)
    return namespace


class BoardMaintenanceTests(unittest.TestCase):
    def test_maintenance_packet_is_acked_and_enters_upload_mode(self):
        helpers = load_maintenance_helpers()
        process = helpers.get("process_maintenance_command")
        self.assertIsNotNone(process, "board must expose maintenance packet processing")
        if process is None:
            return
        entered = []
        helpers["enter_maintenance_mode"] = lambda: entered.append(True)

        accepted = process(
            ("192.168.4.2", 7807),
            10,
            [],
        )

        self.assertTrue(accepted)
        self.assertEqual(helpers["EXPECTED_SEQ"], 11)
        self.assertEqual(entered, [True])
        self.assertEqual(
            helpers["SOCKET"].sent,
            [(b"LD\x01\x00\x0a", ("192.168.4.2", 7807))],
        )

    def test_maintenance_packet_rejects_gap_without_entering_upload_mode(self):
        helpers = load_maintenance_helpers()
        process = helpers.get("process_maintenance_command")
        self.assertIsNotNone(process, "board must expose maintenance packet processing")
        if process is None:
            return
        entered = []
        helpers["enter_maintenance_mode"] = lambda: entered.append(True)

        accepted = process(
            ("192.168.4.2", 7807),
            12,
            [],
        )

        self.assertFalse(accepted)
        self.assertEqual(helpers["EXPECTED_SEQ"], 10)
        self.assertEqual(entered, [])
        self.assertEqual(
            helpers["SOCKET"].sent,
            [(b"LD\x02\x00\x0a", ("192.168.4.2", 7807))],
        )

    def test_maintenance_packet_rejects_nonempty_payload(self):
        helpers = load_maintenance_helpers()
        process = helpers.get("process_maintenance_command")
        self.assertIsNotNone(process, "board must expose maintenance packet processing")
        if process is None:
            return
        entered = []
        helpers["enter_maintenance_mode"] = lambda: entered.append(True)

        accepted = process(
            ("192.168.4.2", 7807),
            10,
            [1],
        )

        self.assertFalse(accepted)
        self.assertEqual(helpers["EXPECTED_SEQ"], 10)
        self.assertEqual(entered, [])
        self.assertEqual(helpers["SOCKET"].sent, [])

    def test_enter_maintenance_mode_stops_effects_clears_queue_and_closes_socket(self):
        helpers = load_maintenance_helpers()
        enter = helpers.get("enter_maintenance_mode")
        self.assertIsNotNone(enter, "board must expose maintenance mode entry")
        if enter is None:
            return

        socket = helpers["SOCKET"]
        enter()

        self.assertTrue(helpers["MAINTENANCE_MODE"])
        self.assertEqual(helpers["SOCKET_BUFFER"], [])
        self.assertEqual(helpers["EFFECTOR"].stop_calls, [False])
        self.assertEqual(helpers["DRIVER"].clear_calls, 1)
        self.assertTrue(socket.closed)
        self.assertIsNone(helpers["SOCKET"])

    def test_board_reserves_command_f3_for_upload_mode(self):
        source = BOARD_MAIN.read_text(encoding="utf-8") + (BOARD_DIR / "config.py").read_text(encoding="utf-8")

        self.assertIn('MAINTENANCE_COMMAND = b"\\xF3"', source)
        self.assertIn("if cmd == MAINTENANCE_COMMAND:", source)
        self.assertIn("process_maintenance_command(addr, seq, payload)", source)
        self.assertIn("while not MAINTENANCE_MODE:", source)

    def test_board_exposes_restart_and_reset_state_control_codes(self):
        source = BOARD_MAIN.read_text(encoding="utf-8") + (BOARD_DIR / "config.py").read_text(encoding="utf-8")

        self.assertIn('RESTART_COMMAND = b"\\xF4"', source)
        self.assertIn('RESET_STATE_COMMAND = b"\\xF5"', source)
        self.assertIn("machine.reset()", source)

    def test_restart_is_acked_before_machine_reset_and_preserves_state(self):
        helpers = load_maintenance_helpers()
        accepted = helpers["process_restart_command"](
            ("192.168.4.2", 7807),
            10,
            [],
        )

        self.assertTrue(accepted)
        self.assertEqual(helpers["SOCKET"].sent, [(b"LD\x01\x00\x0a", ("192.168.4.2", 7807))])
        self.assertEqual(helpers["EFFECTOR"].stop_calls, [False])
        self.assertEqual(helpers["machine"].reset_calls, 1)
        self.assertEqual(helpers["os"].removed, [])

    def test_reset_state_deletes_state_bin_before_ack_and_reset(self):
        helpers = load_maintenance_helpers()
        accepted = helpers["process_reset_state_command"](
            ("192.168.4.2", 7807),
            10,
            [],
        )

        self.assertTrue(accepted)
        self.assertEqual(helpers["os"].removed, ["state.bin"])
        self.assertEqual(helpers["SOCKET"].sent, [(b"LD\x01\x00\x0a", ("192.168.4.2", 7807))])
        self.assertEqual(helpers["machine"].reset_calls, 1)

    def test_reset_state_does_not_reset_when_state_delete_fails(self):
        helpers = load_maintenance_helpers()
        helpers["os"] = type("FailingFilesystem", (), {
            "stat": lambda self, path: (path,),
            "remove": lambda self, path: (_ for _ in ()).throw(OSError("denied")),
        })()

        accepted = helpers["process_reset_state_command"](
            ("192.168.4.2", 7807),
            10,
            [],
        )

        self.assertFalse(accepted)
        self.assertEqual(helpers["SOCKET"].sent, [])
        self.assertEqual(helpers["machine"].reset_calls, 0)


if __name__ == "__main__":
    unittest.main()
