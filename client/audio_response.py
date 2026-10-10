from __future__ import annotations

import threading
import time
from collections.abc import Sequence

try:
    from .audio_capture import AudioCaptureWorker, WindowsLoopbackBackend
    from .audio_spectrum import AudioFrame, SpectrumAnalyzer
except ImportError:
    from audio_capture import AudioCaptureWorker, WindowsLoopbackBackend
    from audio_spectrum import AudioFrame, SpectrumAnalyzer


def _color(color: Sequence[int]) -> tuple[int, int, int]:
    if len(color) != 3:
        raise ValueError("audio response colors must contain RGB")
    values = tuple(int(channel) for channel in color)
    if any(not 0 <= channel <= 255 for channel in values):
        raise ValueError("audio response color channels must fit in one byte")
    return values


class AudioResponseEffect:
    def __init__(self, controller, capture=None, analyzer=None, backend=None) -> None:
        self.controller = controller
        self.lock = threading.RLock()
        self._capture = capture
        if self._capture is None:
            self._capture = AudioCaptureWorker(
                backend or WindowsLoopbackBackend(),
                analyzer or SpectrumAnalyzer(),
                on_frame=self._on_frame,
                on_status=self._on_capture_status,
            )
        else:
            # Test doubles and alternate capture implementations can expose the
            # callback as an attribute without depending on AudioCaptureWorker.
            if hasattr(self._capture, "on_frame"):
                self._capture.on_frame = self._on_frame
            if hasattr(self._capture, "on_status"):
                self._capture.on_status = self._on_capture_status
        self._active = False
        self._colors: tuple[tuple[int, int, int], ...] = ()
        self._last_frame: AudioFrame | None = None
        self._last_sent_at: float | None = None
        self._capture_status: dict = {}
        self._error = ""
        self._closed = False
        self._frame_event = threading.Event()
        self._sender_thread: threading.Thread | None = None
        self._pending_frame: AudioFrame | None = None
        self._generation = 0
        self._board_active = False

    def activate(self, colors: Sequence[Sequence[int]]) -> dict:
        normalized = tuple(_color(color) for color in colors)
        if not 1 <= len(normalized) <= 8:
            raise ValueError("audio response requires one to eight colors")
        with self.lock:
            if self._closed:
                raise RuntimeError("audio response effect is closed")
            was_active = self._active
            was_board_active = self._board_active
        if was_active or was_board_active:
            self.stop()

        # The board must enter audio mode successfully before capture starts.
        self.controller.start_audio(normalized)
        with self.lock:
            self._colors = normalized
            self._last_frame = None
            self._last_sent_at = None
            self._error = ""
            self._active = True
            self._board_active = True
            self._pending_frame = None
            self._generation += 1
            generation = self._generation
            self._frame_event.clear()
            self._sender_thread = threading.Thread(
                target=self._send_loop,
                args=(generation,),
                name="audio-response-sender",
                daemon=True,
            )
            sender = self._sender_thread
        sender.start()
        try:
            self._capture.start()
        except Exception as error:
            with self.lock:
                self._error = str(error)
            self.stop()
            raise
        with self.lock:
            self._capture_status = dict(self._capture.status())
        return self.status()

    def stop(self) -> None:
        with self.lock:
            active = self._active
            board_active = self._board_active
            self._active = False
            self._board_active = False
            self._generation += 1
            self._pending_frame = None
            sender = self._sender_thread
            self._sender_thread = None
            self._frame_event.set()
        if not active and not board_active and sender is None:
            return

        # AudioCaptureWorker.stop joins its reader/analyzer threads before the
        # reliable board stop command, preventing late frames from crossing a
        # mode boundary.
        self._capture.stop()
        if sender is not None and sender is not threading.current_thread():
            sender.join(timeout=1.0)
        with self.lock:
            self._capture_status = dict(self._capture.status())
        if board_active:
            try:
                self.controller.stop_audio()
            except Exception as error:
                with self.lock:
                    self._error = str(error)

    def close(self) -> None:
        with self.lock:
            self._closed = True
        self.stop()

    def status(self) -> dict:
        now = time.monotonic()
        with self.lock:
            capture_status = dict(self._capture_status)
            try:
                capture_status.update(self._capture.status())
            except Exception as error:
                capture_status["error"] = str(error)
            last_frame = self._last_frame
            last_sent_at = self._last_sent_at
            error = self._error or str(capture_status.get("error") or "")
            active = self._active
            colors = self._colors
        return {
            "active": active,
            "colors": [list(color) for color in colors],
            "capture": capture_status,
            "signal": {
                "bands": list(last_frame.bands) if last_frame is not None else [0] * 8,
                "energy": last_frame.energy if last_frame is not None else 0,
                "beat": last_frame.beat if last_frame is not None else 0,
            },
            "send_age": None if last_sent_at is None else max(0.0, now - last_sent_at),
            "error": error,
        }

    def _on_frame(self, frame: AudioFrame) -> None:
        with self.lock:
            if not self._active:
                return
            self._last_frame = frame
            self._pending_frame = frame
            self._frame_event.set()

    def _send_loop(self, generation: int) -> None:
        while True:
            self._frame_event.wait(0.1)
            with self.lock:
                if generation != self._generation:
                    return
                frame = self._pending_frame
                self._pending_frame = None
                self._frame_event.clear()
                active = self._active
            if frame is None:
                if not active:
                    return
                continue
            try:
                self.controller.send_audio_frame(frame)
            except Exception as error:
                with self.lock:
                    if generation == self._generation:
                        self._error = str(error)
                self.stop()
                return
            with self.lock:
                if generation == self._generation:
                    self._last_sent_at = time.monotonic()

    def _on_capture_status(self, status: dict) -> None:
        with self.lock:
            self._capture_status = dict(status)
            if status.get("error"):
                self._error = str(status["error"])
                self._active = False
                self._frame_event.set()
