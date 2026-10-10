from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Sequence

import numpy as np


class AudioCaptureBackend:
    def start(self) -> None:
        raise NotImplementedError

    def read(self, frame_count: int) -> Sequence[float]:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def status(self) -> dict:
        return {"available": False, "device": None, "error": None}


class WindowsLoopbackBackend(AudioCaptureBackend):
    def __init__(self, sample_rate: int = 48000, block_size: int = 512) -> None:
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self._recorder = None
        self._device_name = None
        self._error = None

    def start(self) -> None:
        try:
            import soundcard as sc

            speaker = sc.default_speaker()
            if speaker is None:
                raise OSError("no default Windows playback device")
            microphone = sc.get_microphone(id=str(speaker.id), include_loopback=True)
            try:
                recorder = microphone.recorder(
                    samplerate=self.sample_rate,
                    channels=2,
                    blocksize=self.block_size,
                )
            except TypeError:
                recorder = microphone.recorder(samplerate=self.sample_rate, channels=2)
            self._recorder = recorder.__enter__()
            self._device_name = getattr(speaker, "name", str(speaker))
            self._error = None
        except Exception as exc:
            self._recorder = None
            self._error = str(exc)
            raise OSError(f"WASAPI loopback unavailable: {exc}") from exc

    def read(self, frame_count: int) -> Sequence[float]:
        if self._recorder is None:
            raise OSError("loopback recorder is not started")
        data = np.asarray(self._recorder.record(numframes=int(frame_count)), dtype=np.float32)
        if data.ndim == 2:
            data = np.mean(data, axis=1, dtype=np.float32)
        return data.reshape(-1)

    def stop(self) -> None:
        recorder, self._recorder = self._recorder, None
        if recorder is not None:
            recorder.__exit__(None, None, None)

    def status(self) -> dict:
        return {
            "available": self._recorder is not None,
            "device": self._device_name,
            "error": self._error,
        }


class AudioCaptureWorker:
    def __init__(
        self,
        backend: AudioCaptureBackend,
        analyzer,
        on_frame: Callable[[object], None] | None = None,
        on_status: Callable[[dict], None] | None = None,
        block_size: int = 512,
    ) -> None:
        self.backend = backend
        self.analyzer = analyzer
        self.on_frame = on_frame
        self.on_status = on_status
        self.block_size = int(block_size)
        self._queue: queue.Queue[Sequence[float] | None] = queue.Queue(maxsize=2)
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._reader_thread: threading.Thread | None = None
        self._analyzer_thread: threading.Thread | None = None
        self._running = False
        self._error: str | None = None
        self._received_blocks = 0
        self._dropped_blocks = 0
        self._last_frame_at: float | None = None

    def start(self) -> None:
        start_error = None
        with self._lock:
            if self._running:
                return
            try:
                self.backend.start()
            except Exception as exc:
                start_error = exc
            else:
                self._stop_event.clear()
                self._error = None
                self._running = True
                self._reader_thread = threading.Thread(target=self._read_loop, name="audio-capture", daemon=True)
                self._analyzer_thread = threading.Thread(target=self._analyze_loop, name="audio-spectrum", daemon=True)
                self._reader_thread.start()
                self._analyzer_thread.start()
        if start_error is not None:
            self._set_error(start_error)
            return
        self._publish_status()

    def stop(self, timeout: float = 1.0) -> None:
        with self._lock:
            if not self._running and self._reader_thread is None and self._analyzer_thread is None:
                return
            self._stop_event.set()
            reader, analyzer = self._reader_thread, self._analyzer_thread

        try:
            self.backend.stop()
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        self._enqueue(None)

        deadline = time.monotonic() + max(0.0, float(timeout))
        for thread in (reader, analyzer):
            if thread is not None:
                thread.join(max(0.0, deadline - time.monotonic()))

        with self._lock:
            self._running = False
            self._reader_thread = None
            self._analyzer_thread = None
        self._publish_status()

    def status(self) -> dict:
        with self._lock:
            backend_status = dict(self.backend.status())
            backend_status.update(
                {
                    "running": self._running and not self._stop_event.is_set(),
                    "error": self._error or backend_status.get("error"),
                    "received_blocks": self._received_blocks,
                    "dropped_blocks": self._dropped_blocks,
                    "last_frame_at": self._last_frame_at,
                }
            )
            return backend_status

    def _read_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                block = self.backend.read(self.block_size)
                if block is None or len(block) == 0:
                    continue
                with self._lock:
                    self._received_blocks += 1
                self._enqueue(block)
            except Exception as exc:
                self._set_error(exc)
                break

    def _analyze_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                block = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if block is None:
                return
            try:
                frames = self.analyzer.process(block)
                for frame in frames:
                    if self.on_frame is not None:
                        self.on_frame(frame)
                    with self._lock:
                        self._last_frame_at = time.monotonic()
            except Exception as exc:
                self._set_error(exc)
                return

    def _enqueue(self, block: Sequence[float] | None) -> None:
        try:
            self._queue.put_nowait(block)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            else:
                with self._lock:
                    self._dropped_blocks += 1
            try:
                self._queue.put_nowait(block)
            except queue.Full:
                if block is not None:
                    with self._lock:
                        self._dropped_blocks += 1

    def _set_error(self, exc: Exception) -> None:
        with self._lock:
            self._error = str(exc)
            self._stop_event.set()
            self._running = False
        try:
            self.backend.stop()
        except Exception as stop_error:
            with self._lock:
                self._error = f"{self._error}; stop failed: {stop_error}"
        self._enqueue(None)
        self._publish_status()

    def _publish_status(self) -> None:
        if self.on_status is not None:
            self.on_status(self.status())
