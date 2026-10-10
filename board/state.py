import _thread

try:
    from .config import LED_COUNT, LED_DOT_PER_LINE, LED_LINE, LED_MAX_BRIGHTNESS
except ImportError:
    from config import LED_COUNT, LED_DOT_PER_LINE, LED_LINE, LED_MAX_BRIGHTNESS


SNAPSHOT_LOCK = _thread.allocate_lock()
LIGHT_SNAPSHOT = {
    "mode": 0,
    "brightness_min": 0,
    "brightness_max": 0,
    "timing": 0,
    "colors": [],
    "matrix": None,
}
LIGHT_EFFECT_PARAMS = {}
GLOBAL_BRIGHTNESS = LED_MAX_BRIGHTNESS
GLOBAL_TIMING_MS = 0
GLOBAL_WHITE_BALANCE = (255, 255, 255)


def _blank_matrix() -> list[list[list[int]]]:
    return [
        [[0, 0, 0] for _ in range(LED_DOT_PER_LINE)]
        for _ in range(LED_LINE)
    ]


def _copy_matrix(matrix: list[list[list[int]]] | None) -> list[list[list[int]]] | None:
    if matrix is None:
        return None
    return [[list(cell) for cell in row] for row in matrix]


def _normalize_rgb(color: tuple[int, int, int] | list[int]) -> list[int]:
    if len(color) != 3:
        raise ValueError("RGB color must contain three channels")
    values = [int(channel) for channel in color]
    if any(channel < 0 or channel > 255 for channel in values):
        raise ValueError("RGB channel must fit in one byte")
    return values


def _snapshot_write(mode: int, brightness_min: int, brightness_max: int, timing: int,
                    colors: list[list[int]] | list[tuple[int, int, int]],
                    matrix: list[list[list[int]]] | None) -> None:
    SNAPSHOT_LOCK.acquire()
    try:
        LIGHT_SNAPSHOT["mode"] = mode
        LIGHT_SNAPSHOT["brightness_min"] = max(0, min(255, int(brightness_min)))
        LIGHT_SNAPSHOT["brightness_max"] = max(0, min(255, int(brightness_max)))
        LIGHT_SNAPSHOT["timing"] = max(0, min(0xFFFF, int(timing)))
        LIGHT_SNAPSHOT["colors"] = [_normalize_rgb(color) for color in colors]
        LIGHT_SNAPSHOT["matrix"] = _copy_matrix(matrix)
        LIGHT_EFFECT_PARAMS.clear()
    finally:
        SNAPSHOT_LOCK.release()


def copy_light_snapshot() -> dict:
    SNAPSHOT_LOCK.acquire()
    try:
        return {
            "mode": LIGHT_SNAPSHOT["mode"],
            "brightness_min": LIGHT_SNAPSHOT["brightness_min"],
            "brightness_max": LIGHT_SNAPSHOT["brightness_max"],
            "timing": LIGHT_SNAPSHOT["timing"],
            "colors": [list(color) for color in LIGHT_SNAPSHOT["colors"]],
            "matrix": _copy_matrix(LIGHT_SNAPSHOT["matrix"]),
        }
    finally:
        SNAPSHOT_LOCK.release()


def get_global_brightness() -> int:
    SNAPSHOT_LOCK.acquire()
    try:
        return GLOBAL_BRIGHTNESS
    finally:
        SNAPSHOT_LOCK.release()


def get_global_timing(default: int = 0) -> int:
    SNAPSHOT_LOCK.acquire()
    try:
        timing = GLOBAL_TIMING_MS
    finally:
        SNAPSHOT_LOCK.release()
    return timing if timing > 0 else max(0, int(default))


def get_global_white_balance() -> tuple[int, int, int]:
    SNAPSHOT_LOCK.acquire()
    try:
        return tuple(GLOBAL_WHITE_BALANCE)
    finally:
        SNAPSHOT_LOCK.release()


def set_global_brightness(value: int) -> int:
    global GLOBAL_BRIGHTNESS
    value = max(0, min(LED_MAX_BRIGHTNESS, int(value)))
    SNAPSHOT_LOCK.acquire()
    try:
        GLOBAL_BRIGHTNESS = value
        LIGHT_SNAPSHOT["brightness_max"] = value
        if LIGHT_SNAPSHOT["mode"] != 2:
            LIGHT_SNAPSHOT["brightness_min"] = value
    finally:
        SNAPSHOT_LOCK.release()
    return value


def set_global_timing(value: int) -> int:
    global GLOBAL_TIMING_MS
    value = max(1, min(0xFFFF, int(value)))
    SNAPSHOT_LOCK.acquire()
    try:
        GLOBAL_TIMING_MS = value
        LIGHT_SNAPSHOT["timing"] = value
    finally:
        SNAPSHOT_LOCK.release()
    return value


def set_global_white_balance(red: int, green: int, blue: int) -> tuple[int, int, int]:
    global GLOBAL_WHITE_BALANCE
    values = tuple(max(0, min(255, int(value))) for value in (red, green, blue))
    SNAPSHOT_LOCK.acquire()
    try:
        GLOBAL_WHITE_BALANCE = values
    finally:
        SNAPSHOT_LOCK.release()
    return values


def initialize_runtime_params(snapshot: dict, white_balance: tuple[int, int, int] = (255, 255, 255)) -> None:
    global GLOBAL_BRIGHTNESS, GLOBAL_TIMING_MS, GLOBAL_WHITE_BALANCE
    white_balance = tuple(max(0, min(255, int(value))) for value in white_balance)
    SNAPSHOT_LOCK.acquire()
    try:
        GLOBAL_BRIGHTNESS = max(0, min(LED_MAX_BRIGHTNESS, int(snapshot.get("brightness_max", 0))))
        GLOBAL_TIMING_MS = max(0, min(0xFFFF, int(snapshot.get("timing", 0))))
        GLOBAL_WHITE_BALANCE = white_balance
    finally:
        SNAPSHOT_LOCK.release()


def reset_light_snapshot() -> None:
    _snapshot_write(0, 0, 0, 0, [], None)


def update_fill_snapshot(color: tuple[int, int, int], brightness: int) -> None:
    _snapshot_write(1, brightness, brightness, get_global_timing(), [color], None)


def update_breathe_snapshot(colors: list[tuple[int, int, int]], dark_brightness: int, bright_brightness: int) -> None:
    _snapshot_write(2, dark_brightness, bright_brightness, get_global_timing(), colors, None)


def update_rainbow_snapshot(brightness: int, timing: int, start_x: int = 0,
                            end_x: int = LED_DOT_PER_LINE - 1, duration: int = 1,
                            pingpong: bool = False) -> None:
    _snapshot_write(3, brightness, brightness, timing, [], None)
    SNAPSHOT_LOCK.acquire()
    try:
        LIGHT_EFFECT_PARAMS.update({
            "start_x": max(0, min(LED_DOT_PER_LINE - 1, int(start_x))),
            "end_x": max(0, min(LED_DOT_PER_LINE - 1, int(end_x))),
            "duration": max(1, min(0xFFFF, int(duration))),
            "pingpong": bool(pingpong),
        })
    finally:
        SNAPSHOT_LOCK.release()


def update_matrix_snapshot(matrix: list[list[list[int]]], brightness: int) -> None:
    if len(matrix) != LED_LINE or any(len(row) != LED_DOT_PER_LINE for row in matrix):
        raise ValueError("matrix dimensions must be 6x144")
    normalized = [[_normalize_rgb(cell) for cell in row] for row in matrix]
    _snapshot_write(4, brightness, brightness, get_global_timing(), [], normalized)


def update_matrix_pixels(pixels: list[list[int]], coordinate_mode: bool) -> None:
    SNAPSHOT_LOCK.acquire()
    try:
        matrix = _copy_matrix(LIGHT_SNAPSHOT["matrix"]) or _blank_matrix()
        brightnesses = []
        for pixel in pixels:
            first, second, brightness, red, green, blue = pixel
            if coordinate_mode:
                x, y = first, second
            else:
                if first < 0 or first >= LED_COUNT:
                    continue
                y, physical_x = divmod(first, LED_DOT_PER_LINE)
                x = physical_x if y % 2 == 0 else LED_DOT_PER_LINE - 1 - physical_x
            if x < 0 or x >= LED_DOT_PER_LINE or y < 0 or y >= LED_LINE:
                continue
            matrix[y][x] = _normalize_rgb((red, green, blue))
            brightnesses.append(max(0, min(255, int(brightness))))
        if not brightnesses:
            return
        LIGHT_SNAPSHOT["mode"] = 4
        LIGHT_SNAPSHOT["brightness_min"] = min(brightnesses)
        LIGHT_SNAPSHOT["brightness_max"] = max(brightnesses)
        LIGHT_SNAPSHOT["timing"] = GLOBAL_TIMING_MS
        LIGHT_SNAPSHOT["colors"] = []
        LIGHT_SNAPSHOT["matrix"] = matrix
        LIGHT_EFFECT_PARAMS.clear()
    finally:
        SNAPSHOT_LOCK.release()


def mark_unknown_snapshot() -> None:
    snapshot = copy_light_snapshot()
    _snapshot_write(0xFF, snapshot["brightness_min"], snapshot["brightness_max"], snapshot["timing"], [], snapshot["matrix"])
