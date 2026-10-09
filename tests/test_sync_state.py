import unittest
import subprocess
import sys
from pathlib import Path

from client.protocol import PacketError
from client.sync_state import (
    SYNC_VERSION,
    SyncSnapshot,
    decode_sync_snapshot,
    encode_sync_snapshot,
)


def matrix_fixture():
    return tuple(
        tuple(((row * 7 + col) & 0xFF, (row * 11 + col * 3) & 0xFF, (row + col * 5) & 0xFF) for col in range(144))
        for row in range(6)
    )


class SyncStateCodecTests(unittest.TestCase):
    def test_script_mode_controller_imports_sync_codec(self):
        client_dir = Path(__file__).parents[1] / "client"
        result = subprocess.run(
            [sys.executable, "-c", "import controller; import sync_state"],
            cwd=client_dir,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_matrix_round_trip_preserves_row_major_colors(self):
        snapshot = SyncSnapshot(
            mode=4,
            brightness_min=12,
            brightness_max=231,
            timing=0x1234,
            colors=((1, 2, 3), (250, 249, 248)),
            matrix=matrix_fixture(),
            white_balance=(255, 190, 110),
        )

        encoded = encode_sync_snapshot(snapshot)
        decoded = decode_sync_snapshot(encoded)

        self.assertEqual(decoded, snapshot)
        self.assertEqual(len(encoded), 1 + 1 + 1 + 1 + 2 + 3 + 1 + 6 + 1 + 864 * 3)
        self.assertEqual(encoded[4:6], b"\x12\x34")

    def test_legacy_sync_payload_defaults_white_balance(self):
        snapshot = SyncSnapshot(1, 10, 200, 0x1234, ((1, 2, 3),), None)
        encoded = encode_sync_snapshot(snapshot)
        legacy = encoded[:6] + encoded[9:]
        legacy = bytes([1]) + legacy[1:]

        decoded = decode_sync_snapshot(legacy)

        self.assertEqual(decoded.white_balance, (255, 255, 255))

    def test_all_supported_modes_round_trip(self):
        for mode in (0, 1, 2, 3, 4, 255):
            with self.subTest(mode=mode):
                snapshot = SyncSnapshot(mode, 0, 255, 99, (), None)
                self.assertEqual(decode_sync_snapshot(encode_sync_snapshot(snapshot)), snapshot)

    def test_thirty_two_colors_are_supported(self):
        colors = tuple((index, index + 1, index + 2) for index in range(32))
        snapshot = SyncSnapshot(2, 1, 2, 3, colors, None)

        self.assertEqual(decode_sync_snapshot(encode_sync_snapshot(snapshot)), snapshot)

    def test_codec_rejects_bad_version_truncated_payload_and_invalid_color_count(self):
        encoded = bytearray(encode_sync_snapshot(SyncSnapshot(1, 0, 0, 0, (), None)))
        encoded[0] = SYNC_VERSION + 1
        with self.assertRaises(PacketError):
            decode_sync_snapshot(encoded)

        with self.assertRaises(PacketError):
            decode_sync_snapshot(encoded[1:])

        invalid_count = bytearray(encode_sync_snapshot(SyncSnapshot(1, 0, 0, 0, (), None)))
        invalid_count[9] = 33
        with self.assertRaises(PacketError):
            decode_sync_snapshot(invalid_count)

    def test_codec_rejects_invalid_matrix_length_and_trailing_bytes(self):
        encoded = bytearray(encode_sync_snapshot(SyncSnapshot(4, 0, 0, 0, (), matrix_fixture())))
        encoded[-1] ^= 0x01
        with self.assertRaises(PacketError):
            decode_sync_snapshot(encoded[:-1])

        with self.assertRaises(PacketError):
            decode_sync_snapshot(bytes(encoded) + b"\x00")

    def test_codec_rejects_invalid_mode_color_and_brightness_values(self):
        for kwargs in (
            {"mode": 5},
            {"brightness_min": -1},
            {"brightness_max": 256},
            {"colors": ((256, 0, 0),)},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    SyncSnapshot(**{
                        "mode": kwargs.get("mode", 0),
                        "brightness_min": kwargs.get("brightness_min", 0),
                        "brightness_max": kwargs.get("brightness_max", 0),
                        "timing": 0,
                        "colors": kwargs.get("colors", ()),
                        "matrix": None,
                    })


if __name__ == "__main__":
    unittest.main()
