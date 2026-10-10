import socket
import threading
import time
import unittest

from client.audio_response import AudioResponseEffect
from client.audio_spectrum import AudioFrame
from client.controller import LEDController
from client.protocol import AUDIO_COMMAND, AUDIO_FRAME_SUBTYPE, decode_packet


class FakeSocket:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.sent = []
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recvfrom(self, size):
        if not self.responses:
            raise AssertionError("realtime audio frame must not wait for ACK")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response, ("192.168.4.1", 7807)

    def close(self):
        return None


class FakeCapture:
    def __init__(self, log):
        self.log = log
        self.on_frame = None
        self._status = {"available": True, "running": False, "error": None}

    def start(self):
        self.log.append("capture_start")
        self._status["running"] = True

    def stop(self):
        self.log.append("capture_stop")
        self._status["running"] = False

    def status(self):
        return dict(self._status)


class FakeAudioController:
    def __init__(self, log):
        self.log = log
        self.connected = True
        self.send_error = None

    def start_audio(self, colors):
        self.log.append(("start_audio", colors))
        return 3

    def send_audio_frame(self, frame):
        if self.send_error is not None:
            raise self.send_error
        self.log.append(("send_audio_frame", frame.frame_seq))

    def stop_audio(self):
        self.log.append("stop_audio")
        return 4


class ControllerAudioResponseTests(unittest.TestCase):
    @staticmethod
    def ack(sequence):
        return b"LD\x01" + int(sequence).to_bytes(2, "big")

    def test_audio_start_and_stop_use_reliable_sequence_path(self):
        sock = FakeSocket([self.ack(7), self.ack(8)])
        controller = LEDController(sock=sock, retries=1)
        controller.connected = True
        controller._sequence = 7

        self.assertEqual(controller.start_audio([(1, 2, 3)]), 7)
        self.assertEqual(controller.stop_audio(), 8)
        self.assertEqual(controller.sequence, 9)
        self.assertEqual(decode_packet(sock.sent[0][0])[0], AUDIO_COMMAND)
        self.assertEqual(decode_packet(sock.sent[0][0])[2], [0, 1, 1, 2, 3])
        self.assertEqual(decode_packet(sock.sent[1][0])[2], [2])

    def test_audio_frame_does_not_wait_for_ack_or_change_reliable_state(self):
        sock = FakeSocket()
        controller = LEDController(sock=sock, retries=1)
        controller.connected = True
        controller._sequence = 10
        controller._history[9] = b"old"
        frame = AudioFrame(0x1234, (1, 2, 3, 4, 5, 6, 7, 8), 200, 99)

        controller.send_audio_frame(frame)

        self.assertEqual(controller.sequence, 10)
        self.assertEqual(controller._history, {9: b"old"})
        command, sequence, payload = decode_packet(sock.sent[-1][0])
        self.assertEqual((command, sequence), (AUDIO_COMMAND, 0))
        self.assertEqual(payload[0], AUDIO_FRAME_SUBTYPE)

    def test_audio_frame_send_does_not_wait_for_reliable_command_lock(self):
        sock = FakeSocket()
        controller = LEDController(sock=sock, retries=1)
        controller.connected = True
        finished = threading.Event()
        controller._lock.acquire()
        try:
            thread = threading.Thread(
                target=lambda: (controller.send_audio_frame(AudioFrame(1, (1,) * 8, 1, 0)), finished.set()),
                daemon=True,
            )
            thread.start()
            self.assertTrue(finished.wait(0.5))
        finally:
            controller._lock.release()

    def test_newest_audio_frame_is_the_last_frame_sent(self):
        sock = FakeSocket()
        controller = LEDController(sock=sock, retries=1)
        controller.connected = True
        controller.send_audio_frame(AudioFrame(1, (1,) * 8, 1, 0))
        controller.send_audio_frame(AudioFrame(2, (2,) * 8, 2, 0))

        self.assertEqual(decode_packet(sock.sent[-1][0])[2][1:3], [0, 2])


class AudioResponseEffectTests(unittest.TestCase):
    def test_capture_starts_only_after_board_audio_start_and_stops_before_board_stop(self):
        log = []
        controller = FakeAudioController(log)
        capture = FakeCapture(log)
        effect = AudioResponseEffect(controller, capture=capture)

        result = effect.activate([(1, 2, 3)])
        self.assertTrue(result["active"])
        self.assertEqual(log[0], ("start_audio", ((1, 2, 3),)))
        self.assertEqual(log[1], "capture_start")

        capture.on_frame = lambda frame: None
        effect.stop()
        self.assertEqual(log[-2:], ["capture_stop", "stop_audio"])

    def test_capture_frame_is_forwarded_and_status_contains_signal_and_error(self):
        log = []
        capture = FakeCapture(log)
        effect = AudioResponseEffect(FakeAudioController(log), capture=capture)
        effect.activate([(1, 2, 3)])

        frame = AudioFrame(5, (10,) * 8, 100, 25)
        effect._on_frame(frame)
        status = effect.status()

        deadline = time.monotonic() + 1
        while ("send_audio_frame", 5) not in log and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(("send_audio_frame", 5), log)
        self.assertEqual(status["signal"]["energy"], 100)
        self.assertEqual(status["signal"]["beat"], 25)
        self.assertEqual(status["error"], "")
        effect.stop()

    def test_frame_send_failure_stops_capture_and_board_audio(self):
        log = []
        controller = FakeAudioController(log)
        controller.send_error = OSError("socket closed")
        capture = FakeCapture(log)
        effect = AudioResponseEffect(controller, capture=capture)
        effect.activate([(1, 2, 3)])

        effect._on_frame(AudioFrame(1, (1,) * 8, 10, 0))
        deadline = time.monotonic() + 1
        while effect.status()["active"] and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertFalse(effect.status()["active"])
        self.assertIn("socket closed", effect.status()["error"])
        self.assertEqual(log[-2:], ["capture_stop", "stop_audio"])


if __name__ == "__main__":
    unittest.main()
