import socket
import unittest

from client.controller import ControllerError, LEDController
from client.protocol import SYNC_RESPONSE, build_packet, build_sync_packet
from client.sync_state import SyncSnapshot, encode_sync_snapshot


class FakeSyncSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recvfrom(self, size):
        if not self.responses:
            raise socket.timeout()
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response, ("192.168.4.1", 7807)

    def close(self):
        return None


def sync_response(snapshot, sequence):
    return build_packet(
        SYNC_RESPONSE[0],
        encode_sync_snapshot(snapshot),
        sequence,
    )


class ControllerSyncTests(unittest.TestCase):
    def test_sync_decodes_board_snapshot_without_advancing_sequence(self):
        snapshot = SyncSnapshot(
            mode=2,
            brightness_min=8,
            brightness_max=180,
            timing=0x1234,
            colors=((1, 2, 3), (4, 5, 6)),
            matrix=None,
        )
        sock = FakeSyncSocket([sync_response(snapshot, 0x0042)])
        controller = LEDController(sock=sock, retries=1)
        controller.connected = True
        controller._sequence = 0x0042

        self.assertEqual(controller.sync(), snapshot)
        self.assertEqual(controller.sequence, 0x0042)
        self.assertEqual([packet for packet, _ in sock.sent], [build_sync_packet()])

    def test_sync_timeout_is_nonfatal_to_an_existing_transport_session(self):
        sock = FakeSyncSocket([socket.timeout()])
        controller = LEDController(sock=sock, retries=1)
        controller.connected = True

        with self.assertRaises(ControllerError):
            controller.sync()

        self.assertTrue(controller.connected)

    def test_sync_rejects_malformed_or_wrong_sequence_responses(self):
        snapshot = SyncSnapshot(1, 0, 255, 0, ((1, 2, 3),), None)
        malformed = b"LD\x04\x00\x08\x00\x10" + b"\x00" * 8
        wrong_sequence = sync_response(snapshot, 0x0041)
        sock = FakeSyncSocket([malformed, wrong_sequence])
        controller = LEDController(sock=sock, retries=2)
        controller.connected = True
        controller._sequence = 0x0042

        with self.assertRaises(ControllerError):
            controller.sync()

        self.assertEqual(len(sock.sent), 2)

    def test_sync_requires_a_connected_controller(self):
        controller = LEDController(sock=FakeSyncSocket([]), retries=1)

        with self.assertRaises(ControllerError):
            controller.sync()


if __name__ == "__main__":
    unittest.main()
