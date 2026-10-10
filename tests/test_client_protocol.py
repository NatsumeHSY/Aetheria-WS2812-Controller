import unittest

from client.protocol import (
    ACK,
    AUDIO_COMMAND,
    AUDIO_FRAME_SUBTYPE,
    AUDIO_START_SUBTYPE,
    AUDIO_STOP_SUBTYPE,
    HEALTH_ACK,
    HEALTH_COMMAND,
    HANDSHAKE,
    PARAM_BRIGHTNESS_COMMAND,
    PARAM_TIMING_COMMAND,
    PARAM_WHITE_BALANCE_COMMAND,
    RESTART_COMMAND,
    RESET_STATE_COMMAND,
    RESEND,
    SYNC_COMMAND,
    PacketError,
    build_packet,
    build_white_balance_packet,
    build_brightness_packet,
    build_audio_frame_packet,
    build_audio_start_packet,
    build_audio_stop_packet,
    build_health_packet,
    build_reset_state_packet,
    build_restart_packet,
    build_sync_packet,
    build_timing_packet,
    crc4_itu,
    decode_packet,
    next_sequence,
    parse_response,
)
from client.controller import LEDController


class ClientProtocolTests(unittest.TestCase):
    def test_audio_start_and_stop_use_effect_command_zero_a(self):
        start = build_audio_start_packet([(1, 2, 3), (4, 5, 6)], sequence=0x1234)
        stop = build_audio_stop_packet(sequence=0x1235)

        self.assertEqual(decode_packet(start), (AUDIO_COMMAND, 0x1234, [AUDIO_START_SUBTYPE, 2, 1, 2, 3, 4, 5, 6]))
        self.assertEqual(decode_packet(stop), (AUDIO_COMMAND, 0x1235, [AUDIO_STOP_SUBTYPE]))

    def test_audio_frame_uses_independent_sequence_and_fixed_payload(self):
        packet = build_audio_frame_packet(0xFFFF, (1, 2, 3, 4, 5, 6, 7, 8), 200, 99)

        command, sequence, payload = decode_packet(packet)
        self.assertEqual(command, AUDIO_COMMAND)
        self.assertEqual(sequence, 0)
        self.assertEqual(payload, [AUDIO_FRAME_SUBTYPE, 0xFF, 0xFF, 200, 99, 1, 2, 3, 4, 5, 6, 7, 8])

    def test_audio_packet_builders_reject_invalid_payload_values(self):
        with self.assertRaises(ValueError):
            build_audio_start_packet([])
        with self.assertRaises(ValueError):
            build_audio_start_packet([(1, 2)])
        with self.assertRaises(ValueError):
            build_audio_frame_packet(0, (1, 2, 3), 0, 0)

    def test_build_and_decode_packet_with_crc4(self):
        packet = build_packet(0x01, [0x10, 0x20], 0x1234)

        self.assertEqual(packet[:7], b"LD\x01\x00\x02\x12\x34")
        self.assertEqual(packet[-1], crc4_itu(0x12 ^ 0x34 ^ 0x10 ^ 0x20))
        self.assertEqual(decode_packet(packet), (b"\x01", 0x1234, [0x10, 0x20]))

    def test_decode_rejects_bad_crc_and_wrong_total_length(self):
        packet = build_packet(0x01, [], 0)

        with self.assertRaises(PacketError):
            decode_packet(packet[:-1] + bytes([packet[-1] ^ 0x01]))

        with self.assertRaises(PacketError):
            decode_packet(packet + b"\x00")

    def test_sequence_wraps(self):
        self.assertEqual(next_sequence(0xFFFE), 0xFFFF)
        self.assertEqual(next_sequence(0xFFFF), 0x0000)

    def test_parse_board_responses(self):
        self.assertEqual(parse_response(b"LD" + ACK + b"\x12\x34"), (ACK, 0x1234))
        self.assertEqual(parse_response(b"LD" + RESEND + b"\xFF\xFF"), (RESEND, 0xFFFF))

    def test_health_packet_is_a_crc_checked_control_packet(self):
        packet = build_health_packet()

        self.assertEqual(packet[:7], b"LD" + HEALTH_COMMAND + b"\x00\x00\x00\x00")
        self.assertEqual(decode_packet(packet), (HEALTH_COMMAND, 0, []))

    def test_sync_packet_is_a_crc_checked_control_packet(self):
        packet = build_sync_packet()

        self.assertEqual(packet[:7], b"LD" + SYNC_COMMAND + b"\x00\x00\x00\x00")
        self.assertEqual(decode_packet(packet), (SYNC_COMMAND, 0, []))

    def test_handshake_uses_f0_control_opcode(self):
        self.assertEqual(HANDSHAKE, b"LD\xF0\x00\x00\x00\x00")

    def test_parameter_packets_use_a_segment_and_big_endian_payloads(self):
        brightness = build_brightness_packet(0xCC, sequence=0x1234)
        timing = build_timing_packet(0x0123, sequence=0x1235)

        self.assertEqual(
            decode_packet(brightness),
            (PARAM_BRIGHTNESS_COMMAND, 0x1234, [0xCC]),
        )
        self.assertEqual(
            decode_packet(timing),
            (PARAM_TIMING_COMMAND, 0x1235, [0x01, 0x23]),
        )

    def test_white_balance_packet_uses_a2_and_three_channel_gains(self):
        packet = build_white_balance_packet(255, 190, 110, sequence=0x1236)

        self.assertEqual(
            decode_packet(packet),
            (PARAM_WHITE_BALANCE_COMMAND, 0x1236, [255, 190, 110]),
        )

    def test_restart_and_reset_state_packets_use_f4_and_f5(self):
        restart = build_restart_packet(0x002A)
        reset_state = build_reset_state_packet(0x002B)

        self.assertEqual(decode_packet(restart), (RESTART_COMMAND, 0x002A, []))
        self.assertEqual(decode_packet(reset_state), (RESET_STATE_COMMAND, 0x002B, []))

    def test_parse_health_response_returns_board_expected_sequence(self):
        self.assertEqual(
            parse_response(b"LD" + HEALTH_ACK + b"\x12\x34"),
            (HEALTH_ACK, 0x1234),
        )

    def test_parse_response_rejects_unknown_response_type(self):
        with self.assertRaises(PacketError):
            parse_response(b"LD\x04\x00\x00")

    def test_rainbow_uses_firmware_effect_command_without_color(self):
        controller = LEDController.__new__(LEDController)
        controller._send_packet = lambda command, payload: (command, bytes(payload))

        command, payload = controller.rainbow(
            brightness=204,
            interval=20,
            duration=20,
            pingpong=True,
        )

        self.assertEqual(command, 0x05)
        self.assertEqual(payload, b"\x00\x8f\xcc\x00\x14\x00\x14\xff")

    def test_transition_uses_target_rgb_brightness_and_duration(self):
        controller = LEDController.__new__(LEDController)
        controller._send_packet = lambda command, payload: (command, bytes(payload))

        command, payload = controller.transition((0x11, 0x22, 0x33, 0xCC), duration=0x1234)

        self.assertEqual(command, 0x09)
        self.assertEqual(payload, b"\x11\x22\x33\xCC\x12\x34")

    def test_controller_parameter_and_reset_commands_use_new_opcode_segments(self):
        controller = LEDController.__new__(LEDController)
        controller.connected = True
        controller._history = {}
        controller._owns_socket = False
        controller._socket = None
        controller._lock = __import__("threading").RLock()
        controller._send_packet = lambda command, payload: (command, bytes(payload))

        self.assertEqual(controller.set_brightness(0x80), (0xA0, b"\x80"))
        self.assertEqual(controller.set_timing(0x0123), (0xA1, b"\x01\x23"))
        self.assertEqual(controller.restart(), (0xF4, b""))
        self.assertEqual(controller.reset_state(), (0xF5, b""))


if __name__ == "__main__":
    unittest.main()
