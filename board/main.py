# import required modules
import socket
import machine
import time
import math
import _thread
import os

try:
    from .config import *
    from .protocol import (
        calculate_packet_crc,
        classify_sequence,
        classify_audio_sequence,
        decode_audio_frame_payload,
        next_sequence,
        restore_health_session,
        validate_packet,
    )
except ImportError:
    from config import *
    from protocol import (
        calculate_packet_crc,
        classify_sequence,
        classify_audio_sequence,
        decode_audio_frame_payload,
        next_sequence,
        restore_health_session,
        validate_packet,
    )

# import runtime state and persistence services
try:
    from .state import (
        LIGHT_EFFECT_PARAMS,
        SNAPSHOT_LOCK,
        _blank_matrix,
        _copy_matrix,
        _normalize_rgb,
        copy_light_snapshot,
        get_global_brightness,
        get_global_timing,
        get_global_white_balance,
        initialize_runtime_params,
        mark_unknown_snapshot,
        reset_light_snapshot,
        set_global_brightness,
        set_global_timing,
        set_global_white_balance,
        update_breathe_snapshot,
        update_fill_snapshot,
        update_matrix_pixels,
        update_matrix_snapshot,
        update_rainbow_snapshot,
    )
    from .persistence import (
        atomic_write_persisted_state,
        decode_persisted_state,
        encode_persisted_state,
    )
    from .led_driver import LedDriver
    from .effects import Effector, interpolate_color_state, rainbow_color, xy2pos
    from .audio_wave import AudioWaveConfig
except ImportError:
    from state import (
        LIGHT_EFFECT_PARAMS,
        SNAPSHOT_LOCK,
        _blank_matrix,
        _copy_matrix,
        _normalize_rgb,
        copy_light_snapshot,
        get_global_brightness,
        get_global_timing,
        get_global_white_balance,
        initialize_runtime_params,
        mark_unknown_snapshot,
        reset_light_snapshot,
        set_global_brightness,
        set_global_timing,
        set_global_white_balance,
        update_breathe_snapshot,
        update_fill_snapshot,
        update_matrix_pixels,
        update_matrix_snapshot,
        update_rainbow_snapshot,
    )
    from persistence import (
        atomic_write_persisted_state,
        decode_persisted_state,
        encode_persisted_state,
    )
    from led_driver import LedDriver
    from effects import Effector, interpolate_color_state, rainbow_color, xy2pos
    from audio_wave import AudioWaveConfig

# initialize application globals
DRIVER: LedDriver = None
EFFECTOR: Effector = None
SOCKET: socket.socket = None
CLIENT_ADDR: tuple[str, int] = None
SOCKET_BUFFER: list[tuple[bytes, int, list]] = []
EXPECTED_SEQ: int = None
AUDIO_FRAME_SEQ: int = None
AUDIO_FRAME_COUNT = 0
AUDIO_COLORS: tuple[tuple[int, int, int], ...] = ()
MAINTENANCE_MODE = False

# state and persistence helpers are imported from sibling modules.

def redraw_static_snapshot() -> None:
    audio_wave = getattr(getattr(globals().get("EFFECTOR"), "audio_wave", None), "active", False)
    if audio_wave:
        return
    snapshot = copy_light_snapshot()
    brightness = get_global_brightness()

    if snapshot["mode"] == 1 and snapshot["colors"]:
        DRIVER.fill(tuple(snapshot["colors"][0]), brightness)
    elif snapshot["mode"] == 4 and snapshot["matrix"] is not None:
        for y, row in enumerate(snapshot["matrix"]):
            for x, color in enumerate(row):
                DRIVER.set_pixel(xy2pos(x, y), tuple(color), brightness, False)
        DRIVER.show()

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
        "white_balance": get_global_white_balance(),
    }

def save_persisted_state() -> bool:
    try:
        state = copy_persisted_state()
        atomic_write_persisted_state(
            encode_persisted_state(
                state["snapshot"],
                state["effect_params"],
                state["white_balance"],
            )
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
    initialize_runtime_params(snapshot, state.get("white_balance", (255, 255, 255)))
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
def build_sync_response(expected_seq: int) -> bytes:
    snapshot = copy_light_snapshot()
    colors = snapshot["colors"]
    mode = snapshot["mode"]
    brightness_min = snapshot["brightness_min"]
    brightness_max = snapshot["brightness_max"]
    timing = snapshot["timing"]
    matrix = snapshot["matrix"]

    audio_effect = getattr(globals().get("EFFECTOR"), "audio_wave", None)
    if getattr(audio_effect, "active", False):
        mode = 5
        colors = [list(color) for color in globals().get("AUDIO_COLORS", ())]
        brightness_min = get_global_brightness()
        brightness_max = brightness_min
        timing = get_global_timing(timing)
        matrix = None

    if len(colors) > 32:
        mode = 0xFF
        colors = []

    payload = bytearray([
        SYNC_VERSION,
        mode,
        brightness_min,
        brightness_max,
    ])
    payload.extend(int(timing).to_bytes(2, "big"))
    payload.extend(get_global_white_balance())
    payload.append(len(colors))
    for color in colors:
        payload.extend(color)

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

def led_set_white_balance(length: int, payload: list) -> None:
    if length != 3:
        return
    set_global_white_balance(payload[0], payload[1], payload[2])
    redraw_static_snapshot()
    save_persisted_state()

def led_show(length: int, payload: list) -> None:
    DRIVER.show()
    if copy_light_snapshot()["mode"] == 4:
        save_persisted_state()

def led_audio_control(length: int, payload: list) -> None:
    if not payload:
        return

    global AUDIO_FRAME_SEQ, AUDIO_FRAME_COUNT, AUDIO_COLORS
    subtype = payload[0]
    if subtype == AUDIO_START_SUBTYPE:
        if length < 2:
            return
        color_count = payload[1]
        if not 1 <= color_count <= 8 or length != 2 + color_count * 3:
            return
        colors = [tuple(payload[index:index + 3]) for index in range(2, length, 3)]
        AUDIO_FRAME_SEQ = None
        AUDIO_FRAME_COUNT = 0
        AUDIO_COLORS = tuple(colors)
        config = AudioWaveConfig(colors, timing_ms=get_global_timing(25))
        EFFECTOR.start_audio(config)
        return

    if subtype == AUDIO_STOP_SUBTYPE and length == 1:
        AUDIO_FRAME_SEQ = None
        AUDIO_FRAME_COUNT = 0
        AUDIO_COLORS = ()
        EFFECTOR.stop_audio(clear=True)

def accept_audio_frame(payload: list) -> bool:
    global AUDIO_FRAME_SEQ, AUDIO_FRAME_COUNT

    try:
        audio_seq, energy, beat, bands = decode_audio_frame_payload(payload)
    except ValueError:
        return False
    status, _ = classify_audio_sequence(AUDIO_FRAME_SEQ, audio_seq)
    if status != "accept":
        return False
    AUDIO_FRAME_SEQ = audio_seq
    AUDIO_FRAME_COUNT += 1
    if AUDIO_FRAME_COUNT == 1 or AUDIO_FRAME_COUNT % 30 == 0:
        print(f"[INFO] Audio frame accepted: seq={audio_seq}, count={AUDIO_FRAME_COUNT}")
    if EFFECTOR is not None:
        EFFECTOR.update_audio((audio_seq, energy, beat, bands))
    return True

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
        AUDIO_COMMAND: led_audio_control,
        PARAM_BRIGHTNESS_COMMAND: led_set_global_brightness,
        PARAM_TIMING_COMMAND: led_set_global_timing,
        PARAM_WHITE_BALANCE_COMMAND: led_set_white_balance,
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

            is_audio_frame = cmd == AUDIO_COMMAND and payload and payload[0] == AUDIO_FRAME_SUBTYPE
            if not is_audio_frame:
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

            if cmd == AUDIO_COMMAND and payload and payload[0] == AUDIO_FRAME_SUBTYPE:
                if addr == CLIENT_ADDR:
                    accept_audio_frame(payload)
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
