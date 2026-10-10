import threading
import time
import unittest

import numpy as np

from client.audio_capture import AudioCaptureWorker
from client.audio_spectrum import AudioFrame


class FakeBackend:
    def __init__(self, blocks=None, error=None):
        self.blocks = list(blocks or [])
        self.error = error
        self.started = 0
        self.stopped = 0
        self.release = threading.Event()

    def start(self):
        self.started += 1

    def read(self, frame_count):
        if self.error is not None:
            raise self.error
        if self.blocks:
            return self.blocks.pop(0)
        self.release.wait(0.01)
        return np.zeros(frame_count, dtype=np.float32)

    def stop(self):
        self.stopped += 1
        self.release.set()

    def status(self):
        return {"available": True, "device": "fake"}


class FakeAnalyzer:
    def __init__(self, delay=0):
        self.delay = delay
        self.calls = 0

    def process(self, samples):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return [AudioFrame(self.calls & 0xFFFF, (1,) * 8, 2, 3)]


class AudioCaptureWorkerTests(unittest.TestCase):
    def test_start_and_stop_are_idempotent(self):
        backend = FakeBackend()
        worker = AudioCaptureWorker(backend, FakeAnalyzer())

        worker.start()
        worker.start()
        worker.stop()
        worker.stop()

        self.assertEqual(backend.started, 1)
        self.assertEqual(backend.stopped, 1)

    def test_pcm_blocks_reach_frame_callback(self):
        received = []
        ready = threading.Event()
        backend = FakeBackend([np.ones(8, dtype=np.float32)])
        worker = AudioCaptureWorker(
            backend,
            FakeAnalyzer(),
            on_frame=lambda frame: (received.append(frame), ready.set()),
        )

        worker.start()
        try:
            self.assertTrue(ready.wait(1))
        finally:
            worker.stop()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].bands, (1,) * 8)

    def test_backend_exception_becomes_error_status(self):
        worker = AudioCaptureWorker(FakeBackend(error=OSError("loopback unavailable")), FakeAnalyzer())

        worker.start()
        try:
            deadline = time.monotonic() + 1
            while worker.status().get("error") is None and time.monotonic() < deadline:
                time.sleep(0.01)
            status = worker.status()
        finally:
            worker.stop()

        self.assertIn("loopback unavailable", status["error"])
        self.assertFalse(status["running"])

    def test_bounded_queue_drops_stale_blocks(self):
        backend = FakeBackend([np.ones(8, dtype=np.float32) for _ in range(12)])
        worker = AudioCaptureWorker(backend, FakeAnalyzer(delay=0.03))

        worker.start()
        try:
            deadline = time.monotonic() + 1
            while worker.status()["dropped_blocks"] == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            dropped = worker.status()["dropped_blocks"]
        finally:
            worker.stop()

        self.assertGreater(dropped, 0)


if __name__ == "__main__":
    unittest.main()
