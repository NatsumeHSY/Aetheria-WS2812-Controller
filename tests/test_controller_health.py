import socket
import unittest

from client.controller import LEDController
from client.protocol import HANDSHAKE, HEALTH_ACK, build_health_packet


class FakeDatagramSocket:
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


class ControllerHealthTests(unittest.TestCase):
    def test_connect_recovers_existing_session_without_handshake(self):
        sock = FakeDatagramSocket([b"LD" + HEALTH_ACK + b"\x12\x34"])
        controller = LEDController(sock=sock, retries=1)

        self.assertTrue(controller.connect())
        self.assertTrue(controller.connected)
        self.assertTrue(controller.last_connect_recovered)
        self.assertEqual(controller.sequence, 0x1234)
        self.assertEqual([packet for packet, _ in sock.sent], [build_health_packet()])

    def test_health_restores_sequence_without_consuming_it(self):
        sock = FakeDatagramSocket([b"LD" + HEALTH_ACK + b"\x00\x42"])
        controller = LEDController(sock=sock, retries=1)
        controller.connected = True
        controller._sequence = 0x0010

        self.assertTrue(controller.health())
        self.assertEqual(controller.sequence, 0x0042)
        self.assertTrue(controller.connected)

    def test_connect_falls_back_to_handshake_after_health_timeout(self):
        sock = FakeDatagramSocket([socket.timeout(), b"ok"])
        controller = LEDController(sock=sock, retries=1)

        self.assertTrue(controller.connect())
        self.assertFalse(controller.last_connect_recovered)
        self.assertEqual([packet for packet, _ in sock.sent], [build_health_packet(), HANDSHAKE])

    def test_failed_health_marks_controller_disconnected(self):
        sock = FakeDatagramSocket([socket.timeout()])
        controller = LEDController(sock=sock, retries=1)
        controller.connected = True

        self.assertFalse(controller.health())
        self.assertFalse(controller.connected)


if __name__ == "__main__":
    unittest.main()
