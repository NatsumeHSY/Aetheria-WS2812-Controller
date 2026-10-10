import json
import tempfile
import unittest
from pathlib import Path

from client.ui_state import UI_STATE_VERSION, UiStateStore, normalize_ui_state


def valid_state():
    return {
        "version": UI_STATE_VERSION,
        "source": "quick",
        "mode": "静态常亮",
        "brightness": 72,
        "speed": 50,
        "colors": ["#112233", "#AABBCC"],
        "paintColor": "#8dc9bc",
        "whiteBalance": [255, 190, 110],
        "matrix144x6": [["#000000" for _ in range(144)] for _ in range(6)],
    }


class UiStateTests(unittest.TestCase):
    def test_white_balance_defaults_for_legacy_ui_state_and_preserves_explicit_values(self):
        state = valid_state()
        state.pop("whiteBalance")

        normalized = normalize_ui_state(state)

        self.assertEqual(normalized["whiteBalance"], [255, 255, 255])
        state["whiteBalance"] = [200, 150, 100]
        self.assertEqual(normalize_ui_state(state)["whiteBalance"], [200, 150, 100])

    def test_white_balance_channels_are_validated(self):
        for value in ([256, 0, 0], [-1, 0, 0], [1, 2], [1, 2, "3"]):
            state = valid_state()
            state["whiteBalance"] = value
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_ui_state(state)

    def test_valid_state_round_trip_and_parent_directory_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "ui_state.json"
            store = UiStateStore(path)

            saved = store.save(valid_state())

            self.assertEqual(saved["version"], UI_STATE_VERSION)
            self.assertEqual(store.load(), saved)
            self.assertTrue(path.is_file())

    def test_corrupt_or_unsupported_state_loads_as_none(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui_state.json"
            path.write_text("not json", encoding="utf-8")
            store = UiStateStore(path)
            self.assertIsNone(store.load())

            path.write_text(json.dumps({**valid_state(), "version": 99}), encoding="utf-8")
            self.assertIsNone(store.load())

    def test_state_requires_an_explicit_version(self):
        state = valid_state()
        del state["version"]

        with self.assertRaises(ValueError):
            normalize_ui_state(state)

    def test_invalid_colors_and_dimensions_are_rejected(self):
        for key, value in (
            ("colors", []),
            ("colors", ["bad"]),
            ("paintColor", "#1234"),
            ("matrix144x6", [["#000000"]]),
        ):
            state = valid_state()
            state[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    normalize_ui_state(state)

    def test_all_black_matrix_is_a_valid_persisted_state(self):
        state = valid_state()
        state["speed"] = 200

        normalized = normalize_ui_state(state)

        self.assertEqual(normalized["matrix144x6"][5][143], "#000000")
        self.assertEqual(normalized["speed"], 200)

    def test_audio_response_mode_round_trips_without_extra_board_fields(self):
        state = valid_state()
        state["mode"] = "音频响应"

        normalized = normalize_ui_state(state)

        self.assertEqual(normalized["mode"], "音频响应")
        self.assertEqual(normalized["colors"], ["#112233", "#aabbcc"])
        self.assertNotIn("audio", normalized)


if __name__ == "__main__":
    unittest.main()
