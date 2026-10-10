import _thread
import time

try:
    from .config import COLOR_BLACK, COLOR_WHITE, LED_COUNT, LED_DOT_PER_LINE, LED_LINE
    from .state import get_global_brightness, get_global_timing
except ImportError:
    from config import COLOR_BLACK, COLOR_WHITE, LED_COUNT, LED_DOT_PER_LINE, LED_LINE
    from state import get_global_brightness, get_global_timing


DEFAULT_CENTERS = ((18, 1), (48, 4), (72, 2), (96, 4), (126, 1))
DEFAULT_TIMING_MS = 25
AUDIO_TIMEOUT_MS = 200
RING_WIDTH = 4
MAX_RADIUS = 180


def _clamp_byte(value: int) -> int:
    return max(0, min(255, int(value)))


def _normalize_color(color) -> tuple[int, int, int]:
    if len(color) != 3:
        raise ValueError("audio wave colors must contain RGB")
    return tuple(_clamp_byte(channel) for channel in color)


def _now_ms() -> int:
    ticks_ms = getattr(time, "ticks_ms", None)
    if ticks_ms is not None:
        return int(ticks_ms())
    return int(time.time() * 1000)


def _elapsed_ms(now: int, then: int) -> int:
    ticks_diff = getattr(time, "ticks_diff", None)
    if ticks_diff is not None:
        return int(ticks_diff(now, then))
    return int(now) - int(then)


def _is_newer_sequence(previous: int | None, current: int) -> bool:
    current &= 0xFFFF
    if previous is None:
        return True
    distance = (current - previous) & 0xFFFF
    return distance != 0 and distance < 0x8000


def _approx_distance(dx: int, dy: int) -> int:
    """Cheap integer Euclidean approximation suitable for every LED frame."""
    dx = abs(int(dx))
    dy = abs(int(dy))
    major = max(dx, dy)
    minor = min(dx, dy)
    return major + (minor * 3 // 8)


class AudioWaveConfig:
    def __init__(self, colors, centers=DEFAULT_CENTERS, timing_ms=DEFAULT_TIMING_MS):
        normalized = tuple(_normalize_color(color) for color in (colors or ()))
        self.colors = normalized or (COLOR_WHITE,)
        self.centers = tuple(
            (max(0, min(LED_DOT_PER_LINE - 1, int(center[0]))),
             max(0, min(LED_LINE - 1, int(center[1]))))
            for center in (centers or DEFAULT_CENTERS)
        ) or DEFAULT_CENTERS
        self.timing_ms = max(1, min(0xFFFF, int(timing_ms or DEFAULT_TIMING_MS)))


class AudioWaveState:
    """Bounded, latest-frame-only state for the board-side water-wave renderer."""

    def __init__(self, config: AudioWaveConfig, clock=None):
        self.config = config
        self._clock = clock or _now_ms
        self._lock = _thread.allocate_lock()
        self._last_frame_seq = None
        self._last_update_ms = self._clock()
        self._active = True
        self._waves = [[0, 0, 0, 0] for _ in config.centers]

    def center_colors(self) -> tuple[tuple[int, int, int], ...]:
        return tuple(self.config.colors[index % len(self.config.colors)] for index in range(len(self.config.centers)))

    def update(self, frame_seq: int, energy: int, beat: int, bands) -> bool:
        frame_seq = int(frame_seq) & 0xFFFF
        bands = tuple(_clamp_byte(value) for value in bands)
        if len(bands) != 8:
            return False

        self._lock.acquire()
        try:
            if not _is_newer_sequence(self._last_frame_seq, frame_seq):
                return False

            energy = _clamp_byte(energy)
            beat = _clamp_byte(beat)
            self._last_frame_seq = frame_seq
            self._last_update_ms = self._clock()
            self._active = True

            center_bands = ((0, 1), (1, 2), (2, 3), (4, 5), (6, 7))
            for index, band_indexes in enumerate(center_bands):
                band_level = max(bands[band_indexes[0]], bands[band_indexes[1]])
                injection = min(255, (band_level * 3 // 4) + (energy // 4) + (beat // 2))
                radius, amplitude, decay, _ = self._waves[index]
                if injection > amplitude:
                    radius = 0
                amplitude = max(amplitude, injection)
                decay = max(1, 1 + (255 - band_level) // 64)
                self._waves[index] = [radius, amplitude, decay, band_level]
            return True
        finally:
            self._lock.release()

    def expired(self, now_ms: int, timeout_ms: int = AUDIO_TIMEOUT_MS) -> bool:
        self._lock.acquire()
        try:
            if not self._active or self._last_update_ms is None:
                return True
            return _elapsed_ms(now_ms, self._last_update_ms) > max(0, int(timeout_ms))
        finally:
            self._lock.release()

    def stop(self) -> None:
        self._lock.acquire()
        try:
            self._active = False
            self._last_frame_seq = None
            self._last_update_ms = None
            self._waves = [[0, 0, 0, 0] for _ in self.config.centers]
        finally:
            self._lock.release()

    def wave_snapshot(self) -> tuple[tuple[int, int, int, int], ...]:
        self._lock.acquire()
        try:
            return tuple(tuple(wave) for wave in self._waves)
        finally:
            self._lock.release()

    def _advance(self, timing_ms: int) -> None:
        step = max(1, min(8, 120 // max(1, int(timing_ms))))
        for wave in self._waves:
            wave[0] = (wave[0] + step) % MAX_RADIUS
            wave[1] = max(0, wave[1] - wave[2])

    def render_frame(self, driver, brightness: int, timing_ms: int) -> None:
        self._lock.acquire()
        try:
            active = self._active
            if active:
                self._advance(timing_ms)
            waves = tuple(tuple(wave) for wave in self._waves)
            centers = self.config.centers
            colors = self.center_colors()
        finally:
            self._lock.release()

        if not active:
            for index in range(LED_COUNT):
                driver.set_pixel(index, COLOR_BLACK, 0, False)
            driver.show()
            return

        brightness = _clamp_byte(brightness)
        for y in range(LED_LINE):
            for x in range(LED_DOT_PER_LINE):
                red = 0
                green = 0
                blue = 0
                for index, (center_x, center_y) in enumerate(centers):
                    radius, amplitude, _, _ = waves[index]
                    if amplitude <= 0:
                        continue
                    distance = _approx_distance(x - center_x, y - center_y)
                    ring_error = abs(distance - radius)
                    if ring_error > RING_WIDTH:
                        continue
                    contribution = amplitude * (RING_WIDTH - ring_error + 1) // (RING_WIDTH + 1)
                    color = colors[index]
                    red += color[0] * contribution // 255
                    green += color[1] * contribution // 255
                    blue += color[2] * contribution // 255
                driver.set_pixel(
                    y * LED_DOT_PER_LINE + (x if y % 2 == 0 else LED_DOT_PER_LINE - 1 - x),
                    (_clamp_byte(red), _clamp_byte(green), _clamp_byte(blue)),
                    brightness,
                    False,
                )
        driver.show()


class AudioWaveEffector:
    def __init__(self, driver, frame_interval_ms: int = DEFAULT_TIMING_MS, clock=None):
        self.driver = driver
        self.frame_interval_ms = max(5, int(frame_interval_ms))
        self._clock = clock or _now_ms
        self._lock = _thread.allocate_lock()
        self._state = None
        self._config = None
        self._generation = 0
        self._running = False

    @property
    def active(self) -> bool:
        self._lock.acquire()
        try:
            return self._running
        finally:
            self._lock.release()

    def start(self, config: AudioWaveConfig) -> None:
        self.stop(clear=False)
        state = AudioWaveState(config, clock=self._clock)
        self._lock.acquire()
        try:
            self._generation += 1
            generation = self._generation
            self._config = config
            self._state = state
            self._running = True
        finally:
            self._lock.release()
        _thread.start_new_thread(self._render_loop, (generation, state))

    def update(self, frame) -> bool:
        self._lock.acquire()
        try:
            state = self._state
            running = self._running
        finally:
            self._lock.release()
        if not running or state is None:
            return False
        if hasattr(frame, "frame_seq"):
            values = (frame.frame_seq, frame.energy, frame.beat, frame.bands)
        else:
            values = frame
        return state.update(*values)

    def stop(self, clear: bool = False) -> None:
        self._lock.acquire()
        try:
            self._generation += 1
            self._running = False
            state = self._state
            self._state = None
            self._config = None
        finally:
            self._lock.release()
        if state is not None:
            state.stop()
        if clear:
            self.driver.clear()

    def _render_loop(self, generation: int, state: AudioWaveState) -> None:
        while True:
            self._lock.acquire()
            try:
                active = self._running and generation == self._generation
                config = self._config
            finally:
                self._lock.release()
            if not active or config is None:
                return
            now = self._clock()
            if state.expired(now):
                self.stop(clear=False)
                return
            state.render_frame(
                self.driver,
                get_global_brightness(),
                get_global_timing(config.timing_ms),
            )
            time.sleep_ms(self.frame_interval_ms)
