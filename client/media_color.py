"""Windows media artwork and the client-owned cover-color effect."""

from __future__ import annotations

import asyncio
import hashlib
import io
import sys
import threading
import time
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

try:
    from .controller import ControllerError
except ImportError:
    from controller import ControllerError


MEDIA_MODE = "媒体封面"
MAX_COVER_BYTES = 5 * 1024 * 1024
TRANSITION_MS = 800


def transition_duration_for_timing(timing_ms: int) -> int:
    """Keep 40 rhythm intervals per media fade, within 200–4000 ms."""
    interval = max(5, min(100, int(timing_ms)))
    return interval * 40


def transition_duration_for_speed(speed: int) -> int:
    """Map the UI's 10–200 speed scale to a fade duration in milliseconds."""
    value = max(10, min(200, int(speed)))
    interval = int(1000 / value + 0.5)  # Match JavaScript Math.round in the slider handler.
    return transition_duration_for_timing(interval)


@dataclass(frozen=True)
class MediaSnapshot:
    playing: bool
    cover: bytes | None = None
    title: str = ""
    artist: str = ""


def extract_theme_color(data: bytes) -> tuple[int, int, int] | None:
    """Pick the largest color cluster, avoiding empty borders when possible."""
    if not data or len(data) > MAX_COVER_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 25_000_000:
                return None
            image.thumbnail((64, 64), Image.Resampling.LANCZOS)
            pixels = [tuple(pixel[:3]) for pixel in image.convert("RGBA").get_flattened_data() if pixel[3] >= 128]
        if not pixels:
            return None
        colored = [
            pixel for pixel in pixels
            if max(pixel) - min(pixel) >= 24 and 24 <= max(pixel) and min(pixel) < 235
        ]
        # Keep grayscale artwork valid; discard black/white borders only when
        # a substantial portion of the artwork actually contains color.
        if len(colored) >= len(pixels) * 0.1:
            pixels = colored
        sample = Image.new("RGB", (len(pixels), 1))
        sample.putdata(pixels)
        quantized = sample.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        counts = quantized.getcolors() or []
        _, index = max(counts, key=lambda pair: pair[0])
        palette = quantized.getpalette()
        return tuple(palette[index * 3:index * 3 + 3])
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None


class WindowsMediaReader:
    """Read GSMTC sessions on the worker's COM apartment, without controlling playback."""

    def __init__(self, manager=None):
        self._manager = manager
        self._apartment = False

    async def _initialize(self):
        if self._manager is not None:
            return
        if sys.platform != "win32":
            raise RuntimeError("媒体封面效果需要 Windows")
        try:
            # Foundation is required for the projected async operation types.
            import winrt.windows.foundation
            from winrt.runtime import ApartmentType, init_apartment
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        except ImportError as error:
            raise RuntimeError("媒体读取依赖缺失，请安装 client/requirements.txt") from error
        if not self._apartment:
            init_apartment(ApartmentType.MULTI_THREADED)
            self._apartment = True
        self._manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()

    @staticmethod
    def _playing(session) -> bool:
        if session is None:
            return False
        try:
            # GSMTC's PLAYING value is 4; paused/stopped sessions are fallback.
            return int(session.get_playback_info().playback_status) == 4
        except OSError:
            return False

    async def read(self) -> MediaSnapshot:
        await self._initialize()
        session = self._manager.get_current_session()
        if not self._playing(session):
            session = next((item for item in self._manager.get_sessions() if self._playing(item)), None)
        if session is None:
            return MediaSnapshot(False)
        properties = await session.try_get_media_properties_async()
        if properties is None or not self._playing(session):
            return MediaSnapshot(False)
        title, artist = properties.title or "", properties.artist or ""
        if properties.thumbnail is None:
            return MediaSnapshot(True, title=title, artist=artist)

        from winrt.windows.storage.streams import Buffer, InputStreamOptions

        stream = await properties.thumbnail.open_read_async()
        try:
            size = int(stream.size)
            if not 0 < size <= MAX_COVER_BYTES:
                return MediaSnapshot(True, title=title, artist=artist)
            buffer = await stream.read_async(Buffer(size), size, InputStreamOptions.NONE)
            data = bytes(memoryview(buffer))
            # Playback may have stopped while a slow artwork stream was read.
            return MediaSnapshot(self._playing(session), data, title, artist)
        finally:
            stream.close()

    def close(self):
        self._manager = None
        if self._apartment:
            from winrt.runtime import uninit_apartment

            uninit_apartment()
            self._apartment = False


class MediaColorEffect:
    """Poll artwork off the UI thread and serialize transitions with mode changes."""

    def __init__(self, controller, reader=None, poll_interval=1.0, autostart=True):
        self.controller = controller
        self.reader = reader or WindowsMediaReader()
        self.lock = threading.RLock()
        self._poll_interval = max(0.05, float(poll_interval))
        self._autostart = autostart
        self._thread = None
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._active = False
        self._suspended = False
        self._generation = 0
        self._default_color = (255, 255, 255)
        self._brightness = 255
        self._duration = TRANSITION_MS
        self._last_target = None
        self._transition_until = 0.0
        self._digest = None
        self._theme_color = None
        self._status = {"active": False, "source": "default", "playing": False, "color": None, "title": "", "artist": "", "error": ""}

    def activate(self, default_color, brightness, duration=TRANSITION_MS):
        color = tuple(int(channel) for channel in default_color)
        brightness, duration = int(brightness), int(duration)
        if len(color) != 3 or any(not 0 <= channel <= 255 for channel in color):
            raise ValueError("default_color must contain three byte channels")
        if not 0 <= brightness <= 255 or not 0 <= duration <= 65535:
            raise ValueError("invalid media brightness or transition duration")
        with self.lock:
            if self._closed.is_set():
                raise RuntimeError("media effect is closed")
            if not self._active or self._suspended:
                self._last_target = None
            self._active = True
            self._suspended = False
            self._generation += 1
            self._default_color, self._brightness, self._duration = color, brightness, duration
            self._status.update(active=True)
            if self._autostart and self._thread is None:
                self._thread = threading.Thread(target=self._run, name="media-cover-color", daemon=True)
                self._thread.start()
            self._wake.set()
            return self.status()

    def deactivate(self):
        # Once this returns an older read/send cannot overwrite another mode.
        with self.lock:
            self._active = False
            self._generation += 1
            self._last_target = None
            self._status.update(active=False)
            self._wake.set()

    def suspend(self):
        """Keep the selected mode, but forbid output until sync and activation."""
        with self.lock:
            self._suspended = True
            self._last_target = None
            self._generation += 1
            self._wake.set()

    def set_brightness(self, value):
        with self.lock:
            changed = self._brightness != int(value)
            self._brightness = int(value)
            # A0 redraws output but does not cancel a running board transition.
            # Repair its old brightness target once, without restarting an
            # already-completed transition on every slider update.
            if self._last_target is not None:
                if changed and time.monotonic() < self._transition_until:
                    self._last_target = None
                else:
                    self._last_target = (*self._last_target[:3], self._brightness)
            self._generation += 1
            self._wake.set()

    def set_duration(self, value):
        duration = max(200, min(4000, int(value)))
        with self.lock:
            if duration == self._duration:
                return
            self._duration = duration
            if self._last_target is not None and time.monotonic() < self._transition_until:
                # Retarget an in-flight fade using the newly selected tempo.
                self._last_target = None
            self._generation += 1
            self._wake.set()

    def status(self):
        with self.lock:
            return dict(self._status, suspended=self._suspended)

    async def refresh(self):
        with self.lock:
            if not self._active or self._suspended:
                return
            if not self.controller.connected:
                self._last_target = None
                return
            generation = self._generation
            default, brightness, duration = self._default_color, self._brightness, self._duration
        error = ""
        try:
            snapshot = await asyncio.wait_for(self.reader.read(), timeout=3)
            color = None
            if snapshot.playing and snapshot.cover:
                digest = hashlib.sha256(snapshot.cover).digest()
                if digest != self._digest:
                    self._theme_color = extract_theme_color(snapshot.cover)
                    self._digest = digest
                color = self._theme_color
        except Exception as exc:
            snapshot, color, error = MediaSnapshot(False), None, str(exc)
        target = (*(color or default), brightness)
        with self.lock:
            if not self._active or self._suspended or generation != self._generation or self._closed.is_set():
                return
            self._status.update(
                playing=snapshot.playing,
                source="cover" if color is not None else "default",
                title=snapshot.title, artist=snapshot.artist, error=error,
            )
            if not self.controller.connected:
                self._last_target = None
                return
            if target != self._last_target:
                try:
                    self.controller.transition(target, duration)
                except (ControllerError, OSError, ValueError) as exc:
                    self._status["error"] = str(exc)
                    return
                self._last_target = target
                self._transition_until = time.monotonic() + duration / 1000
            self._status["color"] = "#%02x%02x%02x" % target[:3]

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while not self._closed.is_set():
                self._wake.clear()
                with self.lock:
                    active = self._active and not self._suspended
                if active:
                    loop.run_until_complete(self.refresh())
                self._wake.wait(self._poll_interval if active else None)
        finally:
            close = getattr(self.reader, "close", None)
            if close is not None:
                close()
            loop.close()

    def close(self):
        self.deactivate()
        self._closed.set()
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
