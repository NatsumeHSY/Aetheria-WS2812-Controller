import ast
import unittest
from pathlib import Path


BOARD_MAIN = Path(__file__).parents[1] / "board" / "main.py"


def load_transition_handler():
    tree = ast.parse(BOARD_MAIN.read_text(encoding="utf-8"))
    wanted = {"led_transition"}
    definitions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    calls = []
    saved = []
    namespace = {
        "set_global_brightness": lambda value: calls.append(("brightness", value)),
        "EFFECTOR": type("FakeEffector", (), {
            "transition": lambda self, target, duration: calls.append(("transition", target, duration)),
        })(),
        "mark_unknown_snapshot": lambda: calls.append(("unknown",)),
        "update_fill_snapshot": lambda color, brightness: calls.append(("snapshot", color, brightness)),
        "save_persisted_state": lambda: saved.append(True),
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(BOARD_MAIN), "exec"), namespace)
    return namespace["led_transition"], calls, saved


class BoardTransitionTests(unittest.TestCase):
    def test_transition_records_target_state_for_sync_and_persistence(self):
        handler, calls, saved = load_transition_handler()

        handler(6, [0x11, 0x22, 0x33, 0xCC, 0x12, 0x34])

        self.assertEqual(calls, [
            ("brightness", 0xCC),
            ("snapshot", (0x11, 0x22, 0x33), 0xCC),
            ("transition", (0x11, 0x22, 0x33, 0xCC), 0x1234),
        ])
        self.assertEqual(saved, [True])


if __name__ == "__main__":
    unittest.main()
