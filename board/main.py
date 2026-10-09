# import required modules
import socket
from machine import Pin
import machine
from neopixel import NeoPixel
import time
import math
import _thread
import os

try:
    from .config import *
    from .protocol import (
        calculate_packet_crc,
        classify_sequence,
        next_sequence,
        restore_health_session,
        validate_packet,
    )
except ImportError:
    from config import *
    from protocol import (
        calculate_packet_crc,
        classify_sequence,
        next_sequence,
        restore_health_session,
        validate_packet,
    )

# initialize global variables
DRIVER: LedDriver = None
EFFECTOR: Effector = None
SOCKET: socket.socket = None
CLIENT_ADDR: tuple[str, int] = None
SOCKET_BUFFER: list[tuple[bytes, int, list]] = []
EXPECTED_SEQ: int = None
MAINTENANCE_MODE = False
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

# define functions
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

def persistence_checksum(data: bytes) -> int:
    crc = 0xffff
    for value in data:
        crc ^= (value & 0xff) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xffff
            else:
                crc = (crc << 1) & 0xffff
    return crc

def encode_persisted_state(snapshot: dict, effect_params: dict | None = None) -> bytes:
    effect_params = effect_params or {}
    mode = int(snapshot.get("mode", 0))
    if mode < 0 or mode > 0xff:
        raise ValueError("persisted mode must fit in one byte")

    brightness_min = max(0, min(255, int(snapshot.get("brightness_min", 0))))
    brightness_max = max(0, min(255, int(snapshot.get("brightness_max", 0))))
    timing = max(0, min(0xffff, int(snapshot.get("timing", 0))))
    colors = snapshot.get("colors") or []
    if len(colors) > PERSISTENCE_MAX_COLORS:
        raise ValueError("too many persisted colors")

    data = bytearray(PERSISTENCE_MAGIC)
    data.append(PERSISTENCE_VERSION)
    data.append(mode)
    data.append(brightness_min)
    data.append(brightness_max)
    data.extend(timing.to_bytes(2, "big"))
    data.append(len(colors))
    for color in colors:
        data.extend(_normalize_rgb(color))

    matrix = snapshot.get("matrix")
    if matrix is None:
        data.append(0)
    else:
        if len(matrix) != LED_LINE or any(len(row) != LED_DOT_PER_LINE for row in matrix):
            raise ValueError("persisted matrix dimensions must be 6x144")
        data.append(1)
        for row in matrix:
            for color in row:
                data.extend(_normalize_rgb(color))

    params = bytearray()
    if mode == 3:
        start_x = max(0, min(LED_DOT_PER_LINE - 1, int(effect_params.get("start_x", 0))))
        end_x = max(0, min(LED_DOT_PER_LINE - 1, int(effect_params.get("end_x", LED_DOT_PER_LINE - 1))))
        duration = max(1, min(0xffff, int(effect_params.get("duration", 1))))
        params.extend((start_x, end_x))
        params.extend(duration.to_bytes(2, "big"))
        params.append(255 if effect_params.get("pingpong", False) else 0)

    data.append(len(params))
    data.extend(params)
    data.extend(persistence_checksum(data).to_bytes(2, "big"))
    return bytes(data)

def decode_persisted_state(data: bytes) -> dict | None:
    if len(data) < 13 or data[:2] != PERSISTENCE_MAGIC:
        return None
    if data[2] != PERSISTENCE_VERSION:
        return None
    if persistence_checksum(data[:-2]) != int.from_bytes(data[-2:], "big"):
        return None

    index = 3
    mode = data[index]
    index += 1
    brightness_min = data[index]
    index += 1
    brightness_max = data[index]
    index += 1
    timing = int.from_bytes(data[index:index + 2], "big")
    index += 2
    color_count = data[index]
    index += 1
    if color_count > PERSISTENCE_MAX_COLORS:
        return None

    colors = []
    color_end = index + color_count * 3
    if color_end > len(data) - 2:
        return None
    for _ in range(color_count):
        colors.append(list(data[index:index + 3]))
        index += 3

    if index >= len(data) - 2:
        return None
    matrix_flag = data[index]
    index += 1
    if matrix_flag not in (0, 1):
        return None

    matrix = None
    if matrix_flag:
        matrix_size = LED_LINE * LED_DOT_PER_LINE * 3
        if index + matrix_size > len(data) - 2:
            return None
        matrix = []
        for _ in range(LED_LINE):
            row = []
            for _ in range(LED_DOT_PER_LINE):
                row.append(list(data[index:index + 3]))
                index += 3
            matrix.append(row)

    if index >= len(data) - 2:
        return None
    params_length = data[index]
    index += 1
    params_end = index + params_length
    if params_end != len(data) - 2:
        return None

    effect_params = {}
    if mode == 3:
        if params_length != 5:
            return None
        effect_params = {
            "start_x": data[index],
            "end_x": data[index + 1],
            "duration": int.from_bytes(data[index + 2:index + 4], "big"),
            "pingpong": data[index + 4] == 255,
        }
    elif params_length:
        return None

    return {
        "snapshot": {
            "mode": mode,
            "brightness_min": brightness_min,
            "brightness_max": brightness_max,
            "timing": timing,
            "colors": colors,
            "matrix": matrix,
        },
        "effect_params": effect_params,
    }

def atomic_write_persisted_state(
    data: bytes,
    path: str = PERSISTENCE_PATH,
    temp_path: str = PERSISTENCE_TEMP_PATH,
    opener=open,
    filesystem=os,
) -> None:
    with opener(temp_path, "wb") as handle:
        handle.write(data)
        flush = getattr(handle, "flush", None)
        if flush is not None:
            flush()

    replace = getattr(filesystem, "replace", None)
    if replace is not None:
        replace(temp_path, path)
        return

    try:
        filesystem.remove(path)
    except OSError:
        pass
    filesystem.rename(temp_path, path)

def _snapshot_write(
    mode: int,
    brightness_min: int,
    brightness_max: int,
    timing: int,
    colors: list[list[int]] | list[tuple[int, int, int]],
    matrix: list[list[list[int]]] | None,
) -> None:
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

def initialize_runtime_params(snapshot: dict) -> None:
    global GLOBAL_BRIGHTNESS, GLOBAL_TIMING_MS

    SNAPSHOT_LOCK.acquire()
    try:
        GLOBAL_BRIGHTNESS = max(0, min(LED_MAX_BRIGHTNESS, int(snapshot.get("brightness_max", 0))))
        GLOBAL_TIMING_MS = max(0, min(0xFFFF, int(snapshot.get("timing", 0))))
    finally:
        SNAPSHOT_LOCK.release()

def redraw_static_snapshot() -> None:
    snapshot = copy_light_snapshot()
    brightness = get_global_brightness()

    if snapshot["mode"] == 1 and snapshot["colors"]:
        DRIVER.fill(tuple(snapshot["colors"][0]), brightness)
    elif snapshot["mode"] == 4 and snapshot["matrix"] is not None:
        for y, row in enumerate(snapshot["matrix"]):
            for x, color in enumerate(row):
                DRIVER.set_pixel(xy2pos(x, y), tuple(color), brightness, False)
        DRIVER.show()

def reset_light_snapshot() -> None:
    _snapshot_write(0, 0, 0, 0, [], None)

def copy_persisted_state() -> dict:
    snapshot = copy_light_snapshot()
    SNAPSHOT_LOCK.acquire()
    try:
        effect_params = dict(LIGHT_EFFECT_PARAMS)
    finally:
        SNAPSHOT_LOCK.release()
    return {
        "snapshot": snapshot,
        "effect_params": effect_params,
    }

def save_persisted_state() -> bool:
    try:
        state = copy_persisted_state()
        atomic_write_persisted_state(
            encode_persisted_state(state["snapshot"], state["effect_params"])
        )
        return True
    except Exception as error:
        print("[WARNING] Failed to save board state:", error)
        return False

def load_persisted_state() -> dict | None:
    try:
        with open(PERSISTENCE_PATH, "rb") as handle:
            return decode_persisted_state(handle.read())
    except Exception:
        return None

def restore_persisted_state() -> bool:
    state = load_persisted_state()
    if state is None:
        return False

    snapshot = state["snapshot"]
    initialize_runtime_params(snapshot)
    mode = snapshot["mode"]
    if mode == 0:
        EFFECTOR.stop()
        reset_light_snapshot()
        return True

    if mode == 1:
        colors = snapshot["colors"]
        if not colors:
            return False
        color = tuple(colors[0])
        brightness = snapshot["brightness_max"]
        update_fill_snapshot(color, brightness)
        DRIVER.fill(color, brightness)
        return True

    if mode == 2:
        colors = snapshot["colors"]
        if not colors:
            return False
        normalized_colors = [tuple(color) for color in colors]
        update_breathe_snapshot(
            normalized_colors,
            snapshot["brightness_min"],
            snapshot["brightness_max"],
        )
        EFFECTOR.breathe(
            normalized_colors,
            snapshot["brightness_min"],
            snapshot["brightness_max"],
        )
        return True

    if mode == 3:
        params = state["effect_params"]
        start_x = params.get("start_x", 0)
        end_x = params.get("end_x", LED_DOT_PER_LINE - 1)
        duration = params.get("duration", 1)
        pingpong = params.get("pingpong", False)
        brightness = snapshot["brightness_max"]
        update_rainbow_snapshot(
            brightness,
            snapshot["timing"],
            start_x,
            end_x,
            duration,
            pingpong,
        )
        EFFECTOR.rainbow(
            start_x,
            end_x,
            brightness,
            snapshot["timing"],
            duration,
            pingpong,
        )
        return True

    if mode == 4:
        matrix = snapshot["matrix"]
        if matrix is None:
            return False
        brightness = snapshot["brightness_max"]
        EFFECTOR.stop(clear=False)
        for y, row in enumerate(matrix):
            for x, color in enumerate(row):
                DRIVER.set_pixel(xy2pos(x, y), tuple(color), brightness, False)
        DRIVER.show()
        update_matrix_snapshot(matrix, brightness)
        return True

    return False

def update_fill_snapshot(color: tuple[int, int, int], brightness: int) -> None:
    _snapshot_write(1, brightness, brightness, get_global_timing(), [color], None)

def update_breathe_snapshot(
    colors: list[tuple[int, int, int]],
    dark_brightness: int,
    bright_brightness: int,
) -> None:
    _snapshot_write(2, dark_brightness, bright_brightness, get_global_timing(), colors, None)

def update_rainbow_snapshot(
    brightness: int,
    timing: int,
    start_x: int = 0,
    end_x: int = LED_DOT_PER_LINE - 1,
    duration: int = 1,
    pingpong: bool = False,
) -> None:
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
    _snapshot_write(
        0xFF,
        snapshot["brightness_min"],
        snapshot["brightness_max"],
        snapshot["timing"],
        [],
        snapshot["matrix"],
    )

def build_sync_response(expected_seq: int) -> bytes:
    snapshot = copy_light_snapshot()
    colors = snapshot["colors"]
    mode = snapshot["mode"]
    if len(colors) > 32:
        mode = 0xFF
        colors = []

    payload = bytearray([
        SYNC_VERSION,
        mode,
        snapshot["brightness_min"],
        snapshot["brightness_max"],
    ])
    payload.extend(int(snapshot["timing"]).to_bytes(2, "big"))
    payload.append(len(colors))
    for color in colors:
        payload.extend(color)

    matrix = snapshot["matrix"]
    payload.append(1 if matrix is not None else 0)
    if matrix is not None:
        for row in matrix:
            for color in row:
                payload.extend(color)

    packet = (
        SOCKET_MAGIC
        + RESPONSE_SYNC
        + len(payload).to_bytes(2, "big")
        + int(expected_seq).to_bytes(2, "big")
        + payload
        + bytes([calculate_packet_crc(int(expected_seq), list(payload))])
    )
    if len(packet) > MAX_PACKET_SIZE:
        raise ValueError("sync response exceeds controller receive limit")
    return packet

def send_sequence_response(addr: tuple[str, int], response: bytes, seq: int) -> None:
    SOCKET.sendto(SOCKET_MAGIC + response + seq.to_bytes(2, "big"), addr)

def enter_maintenance_mode() -> None:
    global MAINTENANCE_MODE, SOCKET, CLIENT_ADDR, EXPECTED_SEQ

    if MAINTENANCE_MODE:
        return

    MAINTENANCE_MODE = True
    SOCKET_BUFFER.clear()
    CLIENT_ADDR = None
    EXPECTED_SEQ = None

    if EFFECTOR is not None:
        EFFECTOR.stop(clear=False)
    if DRIVER is not None:
        DRIVER.clear()

    if SOCKET is not None:
        try:
            SOCKET.close()
        except Exception:
            pass
        SOCKET = None

def process_maintenance_command(addr: tuple[str, int], seq: int, payload: list) -> bool:
    global EXPECTED_SEQ

    if payload:
        return False
    if addr != CLIENT_ADDR:
        return False

    sequence_status, next_expected = classify_sequence(EXPECTED_SEQ, seq)
    if sequence_status == "gap":
        send_sequence_response(addr, RESPONSE_RESEND, next_expected)
        return False
    if sequence_status == "replay":
        send_sequence_response(addr, RESPONSE_ACK, seq)
        return False

    EXPECTED_SEQ = next_expected
    send_sequence_response(addr, RESPONSE_ACK, seq)
    enter_maintenance_mode()
    return True

def _stop_before_reset() -> None:
    if EFFECTOR is not None:
        EFFECTOR.stop(clear=False)

def process_restart_command(addr: tuple[str, int], seq: int, payload: list) -> bool:
    global EXPECTED_SEQ

    if payload or addr != CLIENT_ADDR:
        return False

    sequence_status, next_expected = classify_sequence(EXPECTED_SEQ, seq)
    if sequence_status == "gap":
        send_sequence_response(addr, RESPONSE_RESEND, next_expected)
        return False
    if sequence_status == "replay":
        send_sequence_response(addr, RESPONSE_ACK, seq)
        return False

    EXPECTED_SEQ = next_expected
    _stop_before_reset()
    send_sequence_response(addr, RESPONSE_ACK, seq)
    time.sleep_ms(50)
    machine.reset()
    return True

def clear_persisted_state() -> bool:
    try:
        os.stat(PERSISTENCE_PATH)
    except OSError as error:
        error_code = getattr(error, "errno", None)
        if error_code is None and getattr(error, "args", None):
            error_code = error.args[0]
        if error_code == 2:
            return True
        print("[WARNING] Failed to inspect board state:", error)
        return False

    try:
        os.remove(PERSISTENCE_PATH)
        return True
    except OSError as error:
        print("[WARNING] Failed to clear board state:", error)
        return False

def process_reset_state_command(addr: tuple[str, int], seq: int, payload: list) -> bool:
    global EXPECTED_SEQ

    if payload or addr != CLIENT_ADDR:
        return False

    sequence_status, next_expected = classify_sequence(EXPECTED_SEQ, seq)
    if sequence_status == "gap":
        send_sequence_response(addr, RESPONSE_RESEND, next_expected)
        return False
    if sequence_status == "replay":
        send_sequence_response(addr, RESPONSE_ACK, seq)
        return False

    if not clear_persisted_state():
        return False

    EXPECTED_SEQ = next_expected
    _stop_before_reset()
    send_sequence_response(addr, RESPONSE_ACK, seq)
    time.sleep_ms(50)
    machine.reset()
    return True

def xy2pos(x: int, y: int) -> int:
    if y % 2 == 0:
        # even row: left -> right
        return x + y * LED_DOT_PER_LINE
    else:
        # odd row: right -> left
        return (LED_DOT_PER_LINE - 1 - x) + y * LED_DOT_PER_LINE

def rainbow_color(position: int) -> tuple[int, int, int]:
    position = position % 256
    if position < 85:
        return (position * 3, 255 - position * 3, 0)
    if position < 170:
        position -= 85
        return (255 - position * 3, 0, position * 3)
    position -= 170
    return (0, position * 3, 255 - position * 3)

def interpolate_color_state(start: tuple[int, int, int, int], target: tuple[int, int, int, int], step: int, steps: int) -> tuple[int, int, int, int]:
    if steps <= 0 or step >= steps:
        return target
    if step <= 0:
        return start

    values = []
    for index in range(4):
        delta = target[index] - start[index]
        if delta >= 0:
            value = start[index] + (delta * step) // steps
        else:
            value = start[index] - ((-delta * step) // steps)
        values.append(value)
    return tuple(values)

class LedDriver:
    def __init__(self) -> None:
        self.np = NeoPixel(Pin(LED_PIN, Pin.OUT), LED_COUNT)
        self.current_state = (0, 0, 0, 0)
    
    def begin(self) -> None:
        self.np.fill(COLOR_BLACK)
        self.np.write()
        self.current_state = (0, 0, 0, 0)

    def set_pixel(self, index: int, color: tuple[int, int, int], brightness: int = 255, auto_write: bool = False) -> None:
        r_int = int(color[0])
        g_int = int(color[1])
        b_int = int(color[2])
        brightness = int(brightness)

        if brightness > LED_MAX_BRIGHTNESS:
            brightness = LED_MAX_BRIGHTNESS
        elif brightness < LED_MIN_BRIGHTNESS:
            brightness = LED_MIN_BRIGHTNESS
        
        if index < 0 or index >= LED_COUNT:
            return
        
        r = (r_int * brightness) // 255
        g = (g_int * brightness) // 255
        b = (b_int * brightness) // 255
        self.np[index] = (r, g, b)
        if auto_write:
            self.np.write()

    def show(self):
        self.np.write()
    
    def fill(self, color: tuple[int, int, int], brightness: int = 255) -> None:
        r_int = int(color[0])
        g_int = int(color[1])
        b_int = int(color[2])
        brightness = int(brightness)

        if brightness > LED_MAX_BRIGHTNESS:
            brightness = LED_MAX_BRIGHTNESS
        elif brightness < LED_MIN_BRIGHTNESS:
            brightness = LED_MIN_BRIGHTNESS

        r = (r_int * brightness) // 255
        g = (g_int * brightness) // 255
        b = (b_int * brightness) // 255
        self.np.fill((r, g, b))
        self.np.write()
        self.current_state = (r_int, g_int, b_int, brightness)
    
    def clear(self) -> None:
        self.np.fill(COLOR_BLACK)
        self.np.write()
        self.current_state = (0, 0, 0, 0)

class Effector:
    def __init__(self, driver: LedDriver) -> None:
        self.driver = driver
        self.interrupt_flag = True
        self._effect_generation = 0
        self._effect_lock = _thread.allocate_lock()

    def _start_effect(self, clear: bool = True) -> int:
        self.stop(clear=clear)
        self._effect_lock.acquire()
        try:
            self._effect_generation += 1
            self.interrupt_flag = False
            return self._effect_generation
        finally:
            self._effect_lock.release()

    def _effect_active(self, generation: int) -> bool:
        self._effect_lock.acquire()
        try:
            return generation == self._effect_generation and not self.interrupt_flag
        finally:
            self._effect_lock.release()

    def _begin_frame(self, generation: int) -> bool:
        self._effect_lock.acquire()
        if generation != self._effect_generation or self.interrupt_flag:
            self._effect_lock.release()
            return False
        return True

    def _end_frame(self) -> None:
        self.driver.show()
        self._effect_lock.release()

    def _fill_frame(self, generation: int, color: tuple[int, int, int], brightness: int = None) -> bool:
        self._effect_lock.acquire()
        try:
            if generation != self._effect_generation or self.interrupt_flag:
                return False
            if brightness is None:
                self.driver.fill(color)
            else:
                self.driver.fill(color, min(brightness, get_global_brightness()))
            return True
        finally:
            self._effect_lock.release()
    
    def stop(self, clear: bool = True) -> None:
        self._effect_lock.acquire()
        try:
            self._effect_generation += 1
            self.interrupt_flag = True
            if clear:
                self.driver.clear()
        finally:
            self._effect_lock.release()
    
    def fade(self, color: tuple[int, int, int] = COLOR_WHITE, start_brightness: int = 0,end_brightness: int = 255) -> None:
        generation = self._start_effect()

        def effect() -> None:
            if start_brightness < end_brightness:
                brightness_range = range(start_brightness, end_brightness + 1)
            else:
                brightness_range = range(start_brightness, end_brightness - 1, -1)

            for bright in  brightness_range:
                if not self._fill_frame(generation, color, bright):
                    return
        
        _thread.start_new_thread(effect, ())

    def transition(self, target: tuple[int, int, int, int], duration: int = 500) -> None:
        start = self.driver.current_state
        target = (
            max(0, min(255, int(target[0]))),
            max(0, min(255, int(target[1]))),
            max(0, min(255, int(target[2]))),
            max(0, min(255, int(target[3]))),
        )
        duration = max(0, int(duration))

        generation = self._start_effect(clear=False)

        steps = max(1, duration // 10)
        interval = max(1, duration // steps) if duration else 1

        def effect() -> None:
            for step in range(steps + 1):
                state = interpolate_color_state(start, target, step, steps)
                if not self._fill_frame(generation, (state[0], state[1], state[2]), state[3]):
                    return

                if step < steps:
                    time.sleep_ms(interval)

        _thread.start_new_thread(effect, ())
    
    def breathe(self, colors: list[tuple[int, int, int]] = [COLOR_WHITE], dark_brightness: int = 0, bright_brightness: int = 255) -> None:
        generation = self._start_effect()

        # check if dark_brightness and bright_brightness are valid
        if dark_brightness > bright_brightness:
            dark_brightness, bright_brightness = bright_brightness, dark_brightness
        
        def effect() -> None:
            color_idx = 0
            steps = max(1, LED_MAX_BRIGHTNESS - dark_brightness)

            while self._effect_active(generation):
                c1 = colors[color_idx]
                c2 = colors[(color_idx + 1) % len(colors)]

                for step in range(steps + 1):
                    if not self._effect_active(generation):
                        return

                    t = step / steps

                    # 呼吸曲线（亮度）
                    k_breathe = 0.5 * (1 - math.cos(2 * math.pi * t))

                    current_bright = max(dark_brightness, get_global_brightness())
                    brightness = dark_brightness + (current_bright - dark_brightness) * k_breathe
                    factor = brightness / 255

                    # 颜色渐变（线性插值）
                    r = int((c1[0] * (1 - t) + c2[0] * t) * factor)
                    g = int((c1[1] * (1 - t) + c2[1] * t) * factor)
                    b = int((c1[2] * (1 - t) + c2[2] * t) * factor)

                    if not self._fill_frame(generation, (r, g, b)):
                        return

                    time.sleep_ms(get_global_timing(20))

                # 下一组颜色
                color_idx = (color_idx + 1) % len(colors)

        _thread.start_new_thread(effect, ())
    
    def blink(self, color: tuple[int, int, int] = COLOR_WHITE, dark_brightness: int = 0, bright_brightness: int = 255, count: int = 1, interval: int = 500) -> None:
        generation = self._start_effect()

        if dark_brightness > bright_brightness:
            dark_brightness, bright_brightness = bright_brightness, dark_brightness

        def blink_once() -> None:
            current_bright = min(bright_brightness, get_global_brightness())
            current_interval = get_global_timing(interval)
            if not self._fill_frame(generation, color, current_bright):
                return False
            time.sleep_ms(current_interval)
            if not self._fill_frame(generation, color, dark_brightness):
                return False
            time.sleep_ms(current_interval)
            return True
        
        def effect() -> None:
            if count == 0:
                while True:
                    if not self._effect_active(generation):
                        return

                    if not blink_once():
                        return
            else:
                for _ in range(count):
                    if not self._effect_active(generation):
                        return

                    if not blink_once():
                        return
        
        _thread.start_new_thread(effect, ())
    
    def scan_line_x(self, color: tuple[int, int, int] = COLOR_WHITE,
                    start_x: int = 0, end_x: int = LED_DOT_PER_LINE - 1, brightness: int = 255,
                    interval: int = 500, duration: int = 1,
                    pingpong: bool = False, rainbow: bool = False) -> None:
        
        generation = self._start_effect()

        if start_x > end_x:
            if start_x >= LED_DOT_PER_LINE:
                start_x = LED_DOT_PER_LINE - 1
            if end_x < 0:
                end_x = 0
        else:
            if start_x < 0:
                start_x = 0
            if end_x >= LED_DOT_PER_LINE:
                end_x = LED_DOT_PER_LINE - 1

        def effect(start_x: int, end_x: int) -> None:
            last_x = None

            while self._effect_active(generation):
                if start_x < end_x:
                    x_range = range(start_x, end_x + 1)
                else:
                    x_range = range(start_x, end_x - 1, -1)

                for x in x_range:
                    if not self._begin_frame(generation):
                        return
                        
                    frame_color = rainbow_color(x) if rainbow else color
                    for y in range(LED_LINE):
                        pos = xy2pos(x, y)
                        self.driver.set_pixel(pos, frame_color, min(brightness, get_global_brightness()), False)
                        if last_x is not None and last_x != x:
                            self.driver.set_pixel(xy2pos(last_x, y), COLOR_BLACK, 0, False)
                    last_x = x
                    self._end_frame()

                    time.sleep_ms(get_global_timing(duration))
                
                if pingpong:
                    start_x, end_x = end_x, start_x

                if not pingpong:
                    self._effect_lock.acquire()
                    try:
                        if generation == self._effect_generation and not self.interrupt_flag:
                            self.driver.clear()
                    finally:
                        self._effect_lock.release()
                    time.sleep_ms(interval)
        
        _thread.start_new_thread(effect, (start_x, end_x))

    def rainbow(self,
                start_x: int = 0, end_x: int = LED_DOT_PER_LINE - 1,
                brightness: int = 255, interval: int = 500,
                duration: int = 1, pingpong: bool = False) -> None:
        generation = self._start_effect()

        if start_x > end_x:
            if start_x >= LED_DOT_PER_LINE:
                start_x = LED_DOT_PER_LINE - 1
            if end_x < 0:
                end_x = 0
        else:
            if start_x < 0:
                start_x = 0
            if end_x >= LED_DOT_PER_LINE:
                end_x = LED_DOT_PER_LINE - 1

        duration = max(1, int(duration))

        def effect(start_x: int, end_x: int) -> None:
            hue_offset = 0
            hue_phase = 0

            while self._effect_active(generation):
                if start_x < end_x:
                    x_range = range(start_x, end_x + 1)
                else:
                    x_range = range(start_x, end_x - 1, -1)

                span = max(1, abs(end_x - start_x))
                if not self._begin_frame(generation):
                    return

                for x in x_range:
                    hue = hue_offset + ((x - start_x) * 255 // span)
                    color = rainbow_color(hue)
                    for y in range(LED_LINE):
                        self.driver.set_pixel(xy2pos(x, y), color, get_global_brightness(), False)
                self._end_frame()
                time.sleep_ms(RAINBOW_FRAME_INTERVAL)

                hue_phase += RAINBOW_HUE_STEP
                hue_offset = (hue_phase // RAINBOW_HUE_DIVISOR) % 256
                if pingpong:
                    start_x, end_x = end_x, start_x

        _thread.start_new_thread(effect, (start_x, end_x))

    def floor_tile_x(self, color: tuple[int, int, int] = COLOR_WHITE,
                     start_x: int = 0, end_x: int = LED_DOT_PER_LINE - 1, brightness: int = 255,
                     loop: bool = False, fade: bool = True, fade_reverse: bool = False,
                     duration: int = 1, fade_delay: int = 1, interval: int = 500) -> None:
        
        generation = self._start_effect()

        if start_x > end_x:
            if start_x >= LED_DOT_PER_LINE:
                start_x = LED_DOT_PER_LINE - 1
            if end_x < 0:
                end_x = 0
        else:
            if start_x < 0:
                start_x = 0
            if end_x >= LED_DOT_PER_LINE:
                end_x = LED_DOT_PER_LINE - 1
        
        def floor_from_side(color: tuple[int, int, int], start_x: int, end_x: int) -> None:
            if start_x < end_x:
                x_range = range(start_x, end_x + 1)
            else:
                x_range = range(start_x, end_x - 1, -1)
            
            for x in x_range:
                if not self._effect_active(generation):
                    return

                if not self._begin_frame(generation):
                    return
                for y in range(LED_LINE):
                    pos = xy2pos(x, y)
                    self.driver.set_pixel(pos, color, min(brightness, get_global_brightness()), False)
                self._end_frame()

                time.sleep_ms(get_global_timing(duration))

        def effect() -> None:
            while self._effect_active(generation):
                floor_from_side(color, start_x, end_x)

                if fade:
                    time.sleep_ms(fade_delay)

                    if fade_reverse:
                        floor_from_side(COLOR_BLACK, end_x, start_x)
                    else:
                        floor_from_side(COLOR_BLACK, start_x, end_x)
                
                if loop:
                    time.sleep_ms(get_global_timing(interval))
                    self._fill_frame(generation, COLOR_BLACK, 0)
                else:
                    return
        
        _thread.start_new_thread(effect, ())
    
    def fill_range(self, color: tuple[int, int, int] = COLOR_WHITE,
                   start_xy: tuple[int, int] = (0, 0), end_xy: tuple[int, int] = (LED_DOT_PER_LINE - 1, LED_LINE - 1),
                   brightness: int = 255) -> None:
        
        self.stop()

        start_pos = xy2pos(start_xy[0], start_xy[1])
        end_pos = xy2pos(end_xy[0], end_xy[1])

        if start_pos > end_pos:
            start_pos, end_pos = end_pos, start_pos
        
        if start_pos < 0:
            start_pos = 0
        if end_pos >= LED_COUNT:
            end_pos = LED_COUNT - 1

        for i in range(start_pos, end_pos + 1):
            self.driver.set_pixel(i, color, brightness, False)
        
        self.driver.show()
    
    def fill_square(self, color: tuple[int, int, int] = COLOR_WHITE,
                    start_xy: tuple[int, int] = (0, 0), end_xy: tuple[int, int] = (LED_DOT_PER_LINE - 1, LED_LINE - 1),
                    brightness: int = 255) -> None:
        
        self.stop()

        w = abs(end_xy[0] - start_xy[0]) + 1
        h = abs(end_xy[1] - start_xy[1]) + 1

        if start_xy[0] + w > LED_DOT_PER_LINE:
            w = LED_DOT_PER_LINE - start_xy[0]
        if start_xy[1] + h > LED_LINE:
            h = LED_LINE - start_xy[1]
        
        start_pos = xy2pos(start_xy[0], start_xy[1])
        for y in range(h):
            for x in range(w):
                pos = start_pos + x + y * LED_DOT_PER_LINE
                self.driver.set_pixel(pos, color, brightness, False)
        
        self.driver.show()

def start_socket() -> socket.socket | None:
    print(f"[INFO] Socket starting on port: {SOCKET_PORT} ...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("0.0.0.0", SOCKET_PORT))
        print("[INFO] Socket started successfully")
        return s
    except Exception as e:
        print("[ERROR] Failed to start socket:", e)
        return None

def wait_for_client() -> tuple[str, int] | None:
    global CLIENT_ADDR, EXPECTED_SEQ

    print("[INFO] Waiting for client...")
    while True:
        try:
            data, addr = SOCKET.recvfrom(8)
            magic = data[:2]
            cmd = data[2:3]

            print(
                f"[INFO] Received data from {addr[0]}:{addr[1]}:",
                data[:20],
                "..." if len(data) > 20 else "",
                "\n\tMagic:",
                magic,
                "Command:",
                cmd
            )
            
            if data != SOCKET_MAGIC + b"\xF0\x00\x00\x00\x00":
                print("[ERROR] Invalid magic header")
                continue
            
            if cmd == b"\xF0":
                CLIENT_ADDR = addr
                EXPECTED_SEQ = None
                print(f"[INFO] Client connected: {addr[0]}:{addr[1]}")
                SOCKET.sendto(b"ok", addr)
                break
        except:
            continue

def led_clear(length: int, payload: list) -> None:
    EFFECTOR.stop()
    set_global_brightness(0)
    reset_light_snapshot()
    save_persisted_state()
def led_fill(length: int, payload: list) -> None:
    if length != 4: return
    
    brightness = payload[0]
    color = (payload[1], payload[2], payload[3])

    EFFECTOR.stop(clear=False)
    set_global_brightness(brightness)
    update_fill_snapshot(color, brightness)
    DRIVER.fill(color, get_global_brightness())
    save_persisted_state()
def led_blink(length: int, payload: list) -> None:
    if length != 8: return
    
    """
    (method) def blink(
        color: tuple[int, int, int] = COLOR_WHITE,
        dark_brightness: int = 0,
        bright_brightness: int = 255,
        count: int = 1,
        interval: int = 500
    ) -> None
    """
    set_global_brightness(payload[1])
    mark_unknown_snapshot()
    EFFECTOR.blink((payload[5], payload[6], payload[7]), payload[0], payload[1], payload[2], int(hex(payload[3]) + hex(payload[4])[2:], 16))
def led_fade(length: int, payload: list) -> None:
    if length != 5: return

    """
    (method) def fade(
        color: tuple[int, int, int] = COLOR_WHITE,
        start_brightness: int = 0,
        end_brightness: int = 255
    ) -> None
    """
    mark_unknown_snapshot()
    EFFECTOR.fade((payload[2], payload[3], payload[4]), payload[0], payload[1])
def led_transition(length: int, payload: list) -> None:
    if length != 6: return

    duration = int(hex(payload[4]) + hex(payload[5])[2:], 16)
    target = (payload[0], payload[1], payload[2], payload[3])
    set_global_brightness(target[3])
    update_fill_snapshot((target[0], target[1], target[2]), target[3])
    EFFECTOR.transition(target, duration)
    save_persisted_state()
def led_breathe(length: int, payload: list) -> None:
    if (length - 2) % 3 != 0: return
    
    colors = [payload[i:i+3] for i in range(2, length - 2, 3)]
    """
    (method) def breathe(
        colors: list[tuple[int, int, int]] = [COLOR_WHITE],
        dark_brightness: int = 0,
        bright_brightness: int = 255
    ) -> None
    """
    set_global_brightness(payload[1])
    update_breathe_snapshot(colors, payload[0], payload[1])
    EFFECTOR.breathe(colors, payload[0], payload[1])
    save_persisted_state()
def led_rainbow(length: int, payload: list) -> None:
    if length != 8: return

    interval = int(hex(payload[3]) + hex(payload[4])[2:], 16)
    duration = int(hex(payload[5]) + hex(payload[6])[2:], 16)
    pingpong = payload[7] == 255
    set_global_brightness(payload[2])
    update_rainbow_snapshot(
        payload[2],
        RAINBOW_FRAME_INTERVAL,
        payload[0],
        payload[1],
        duration,
        pingpong,
    )
    EFFECTOR.rainbow(
        payload[0], payload[1], payload[2],
        interval,
        duration,
        pingpong,
    )
    save_persisted_state()
def led_floor_tile_x(length: int, payload: list) -> None:
    if length != 15: return
    
    """
    (method) def floor_tile_x(
        color: tuple[int, int, int] = COLOR_WHITE,
        start_x: int = 0,
        end_x: int = LED_DOT_PER_LINE - 1,
        brightness: int = 255,
        loop: bool = False,
        fade: bool = True,
        fade_reverse: bool = False,
        duration: int = 1,
        fade_delay: int = 1,
        interval: int = 500
    ) -> None
    """
    mark_unknown_snapshot()
    EFFECTOR.floor_tile_x(
        (payload[12], payload[13], payload[14]),
        payload[0], payload[1], payload[2],
        payload[3] == 255, payload[4] == 255, payload[5] == 255,
        int(hex(payload[6]) + hex(payload[7])[2:], 16),
        int(hex(payload[8]) + hex(payload[9])[2:], 16),
        int(hex(payload[10]) + hex(payload[11])[2:], 16),
    )
def led_set_pixel(length: int, payload: list) -> None:
    if length < 7 or (length - 1) % 6 != 0: return
    
    led_data = [payload[i:i+6] for i in range(1, len(payload), 6)]
    EFFECTOR.stop(clear=False)
    set_global_brightness(max(led[2] for led in led_data))
    """
    (method) def set_pixel(
        index: int,
        color: tuple[int, int, int],
        brightness: int = 255,
        auto_write: bool = False
    ) -> None
    """
    for led in led_data:
        DRIVER.set_pixel(
            int(hex(led[0]) + hex(led[1])[2:], 16) if payload[0] == 0 else xy2pos(led[0], led[1]),
            (led[3], led[4], led[5]),
            led[2], False
        )
    update_matrix_pixels(led_data, payload[0] == 1)

def led_set_global_brightness(length: int, payload: list) -> None:
    if length != 1:
        return
    set_global_brightness(payload[0])
    redraw_static_snapshot()
    save_persisted_state()

def led_set_global_timing(length: int, payload: list) -> None:
    if length != 2:
        return
    timing = (payload[0] << 8) | payload[1]
    set_global_timing(timing)
    save_persisted_state()
def led_show(length: int, payload: list) -> None:
    DRIVER.show()
    if copy_light_snapshot()["mode"] == 4:
        save_persisted_state()

def exec_socket_buffer() -> None:
    effect_map = {
        b"\x00": led_clear,
        b"\x01": led_fill,
        b"\x02": led_blink,
        b"\x03": led_fade,
        b"\x04": led_breathe,
        b"\x05": led_rainbow,
        b"\x09": led_transition,
        b"\x06": led_floor_tile_x,
        b"\x07": led_set_pixel,
        b"\x08": led_show,
        PARAM_BRIGHTNESS_COMMAND: led_set_global_brightness,
        PARAM_TIMING_COMMAND: led_set_global_timing,
    }

    while not MAINTENANCE_MODE:
        if len(SOCKET_BUFFER) < 1: continue
        buffer = SOCKET_BUFFER.pop(0)
        if buffer is None: continue

        if MAINTENANCE_MODE:
            return

        cmd, length, payload = buffer
        if cmd not in effect_map: continue

        effect_map[cmd](length, payload)

def setup() -> None:
    global DRIVER, EFFECTOR, SOCKET

    SOCKET = start_socket()

    if SOCKET is None:
        os._exit(1)
        return

    DRIVER = LedDriver()
    DRIVER.begin()
    EFFECTOR = Effector(DRIVER)

    if restore_persisted_state():
        wait_for_client()
        return

    DRIVER.fill(COLOR_WHITE)
    time.sleep(3)
    
    EFFECTOR.blink(COLOR_CYAN, 0, 255, 2, 500)
    time.sleep(2)
    EFFECTOR.scan_line_x(pingpong=True, rainbow=True)

    wait_for_client()

    EFFECTOR.floor_tile_x(COLOR_GREEN)

def loop() -> None:
    global CLIENT_ADDR, EXPECTED_SEQ

    _thread.start_new_thread(exec_socket_buffer, ())

    while not MAINTENANCE_MODE:
        try:
            data, addr = SOCKET.recvfrom(6144)
            valid, cmd, seq, payload = validate_packet(data)

            if not valid:
                print(f"[WARNING] Invalid packet from {addr[0]}:{addr[1]}")
                continue

            length = len(payload)

            print(
                f"[INFO] Received data from {addr[0]}:{addr[1]}:",
                data[:20],
                "..." if len(data) > 20 else "",
                "\n\tMagic:",
                data[:2],
                "Command:",
                cmd, 
                f"Length: {length}, Seq: {seq}\n\tPayload: {payload[:20]}{'...' if len(payload) > 20 else ''}"
            )

            if cmd == HEALTH_COMMAND:
                accepted, restored_addr, expected_seq = restore_health_session(
                    CLIENT_ADDR,
                    addr,
                    EXPECTED_SEQ,
                )
                if accepted:
                    CLIENT_ADDR = restored_addr
                    send_sequence_response(addr, RESPONSE_HEALTH, expected_seq)
                continue

            if cmd == SYNC_COMMAND:
                accepted, restored_addr, expected_seq = restore_health_session(
                    CLIENT_ADDR,
                    addr,
                    EXPECTED_SEQ,
                )
                if accepted:
                    CLIENT_ADDR = restored_addr
                    SOCKET.sendto(build_sync_response(expected_seq), addr)
                continue

            if cmd == MAINTENANCE_COMMAND:
                process_maintenance_command(addr, seq, payload)
                continue

            if cmd == RESTART_COMMAND:
                process_restart_command(addr, seq, payload)
                continue

            if cmd == RESET_STATE_COMMAND:
                process_reset_state_command(addr, seq, payload)
                continue

            if addr != CLIENT_ADDR: continue
            sequence_status, next_expected = classify_sequence(EXPECTED_SEQ, seq)

            if sequence_status == "gap":
                print(f"[WARNING] Missing sequence {next_expected}, requesting resend")
                send_sequence_response(addr, RESPONSE_RESEND, next_expected)
                continue

            if sequence_status == "replay":
                print(f"[WARNING] Ignoring replayed sequence {seq}")
                send_sequence_response(addr, RESPONSE_ACK, seq)
                continue

            EXPECTED_SEQ = next_expected
            send_sequence_response(addr, RESPONSE_ACK, seq)
            
            SOCKET_BUFFER.append((cmd, length, payload))
        except:
            if MAINTENANCE_MODE:
                break
            continue

setup()
loop()
# effector.floor_tile_x(COLOR_PINK, 0, LED_DOT_PER_LINE - 1, 255, False, True, False, 1, 1000, 500)
