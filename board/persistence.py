import os

try:
    from .config import (
        LED_DOT_PER_LINE,
        LED_LINE,
        PERSISTENCE_MAGIC,
        PERSISTENCE_MAX_COLORS,
        PERSISTENCE_PATH,
        PERSISTENCE_TEMP_PATH,
        PERSISTENCE_VERSION,
    )
    from .state import _normalize_rgb
except ImportError:
    from config import (
        LED_DOT_PER_LINE,
        LED_LINE,
        PERSISTENCE_MAGIC,
        PERSISTENCE_MAX_COLORS,
        PERSISTENCE_PATH,
        PERSISTENCE_TEMP_PATH,
        PERSISTENCE_VERSION,
    )
    from state import _normalize_rgb


LEGACY_PERSISTENCE_VERSION = 1
DEFAULT_WHITE_BALANCE = (255, 255, 255)


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


def _normalize_white_balance(white_balance) -> tuple[int, int, int]:
    if not isinstance(white_balance, (tuple, list)) or len(white_balance) != 3:
        raise ValueError("white balance must contain three channels")
    return tuple(max(0, min(255, int(value))) for value in white_balance)


def encode_persisted_state(
    snapshot: dict,
    effect_params: dict | None = None,
    white_balance: tuple[int, int, int] = DEFAULT_WHITE_BALANCE,
) -> bytes:
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
    data.extend(_normalize_white_balance(white_balance))
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
    version = data[2]
    if version not in (LEGACY_PERSISTENCE_VERSION, PERSISTENCE_VERSION):
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

    if version == PERSISTENCE_VERSION:
        if index + 3 > len(data) - 2:
            return None
        white_balance = tuple(data[index:index + 3])
        index += 3
    else:
        white_balance = DEFAULT_WHITE_BALANCE

    if index >= len(data) - 2:
        return None
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
        "white_balance": white_balance,
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
