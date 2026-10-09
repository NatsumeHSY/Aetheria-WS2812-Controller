from __future__ import annotations

from dataclasses import dataclass

try:
    from .protocol import PacketError
except ImportError:
    from protocol import PacketError


SYNC_VERSION = 1
MATRIX_ROWS = 6
MATRIX_COLUMNS = 144
MAX_SYNC_COLORS = 32
SUPPORTED_MODES = frozenset((0, 1, 2, 3, 4, 0xFF))
MATRIX_BYTE_LENGTH = MATRIX_ROWS * MATRIX_COLUMNS * 3


def _validate_byte(value: int, field: str) -> int:
    if not isinstance(value, int) or not 0 <= value <= 0xFF:
        raise ValueError(f"{field} must fit in one byte")
    return value


def _normalize_color(color, field: str) -> tuple[int, int, int]:
    if not isinstance(color, (tuple, list)) or len(color) != 3:
        raise ValueError(f"{field} must contain three RGB values")
    return tuple(_validate_byte(value, f"{field}[{index}]") for index, value in enumerate(color))


def _normalize_matrix(matrix) -> tuple[tuple[tuple[int, int, int], ...], ...] | None:
    if matrix is None:
        return None
    if not isinstance(matrix, (tuple, list)) or len(matrix) != MATRIX_ROWS:
        raise ValueError("matrix must contain six rows")
    rows = []
    for row_index, row in enumerate(matrix):
        if not isinstance(row, (tuple, list)) or len(row) != MATRIX_COLUMNS:
            raise ValueError(f"matrix row {row_index} must contain 144 cells")
        rows.append(tuple(_normalize_color(cell, f"matrix[{row_index}][]") for cell in row))
    return tuple(rows)


@dataclass(frozen=True)
class SyncSnapshot:
    mode: int
    brightness_min: int
    brightness_max: int
    timing: int
    colors: tuple[tuple[int, int, int], ...]
    matrix: tuple[tuple[tuple[int, int, int], ...], ...] | None

    def __post_init__(self):
        if not isinstance(self.mode, int) or self.mode not in SUPPORTED_MODES:
            raise ValueError("unsupported sync mode")
        _validate_byte(self.brightness_min, "brightness_min")
        _validate_byte(self.brightness_max, "brightness_max")
        if not isinstance(self.timing, int) or not 0 <= self.timing <= 0xFFFF:
            raise ValueError("timing must fit in two bytes")
        if not isinstance(self.colors, (tuple, list)) or len(self.colors) > MAX_SYNC_COLORS:
            raise ValueError("sync color count must be between 0 and 32")
        colors = tuple(_normalize_color(color, "colors[]") for color in self.colors)
        matrix = _normalize_matrix(self.matrix)
        object.__setattr__(self, "colors", colors)
        object.__setattr__(self, "matrix", matrix)


def encode_sync_snapshot(snapshot: SyncSnapshot) -> bytes:
    if not isinstance(snapshot, SyncSnapshot):
        raise TypeError("snapshot must be a SyncSnapshot")

    payload = bytearray(
        (
            SYNC_VERSION,
            snapshot.mode,
            snapshot.brightness_min,
            snapshot.brightness_max,
        )
    )
    payload.extend(snapshot.timing.to_bytes(2, "big"))
    payload.append(len(snapshot.colors))
    for color in snapshot.colors:
        payload.extend(color)
    payload.append(1 if snapshot.matrix is not None else 0)
    if snapshot.matrix is not None:
        for row in snapshot.matrix:
            for color in row:
                payload.extend(color)
    return bytes(payload)


def _packet_error(message: str) -> PacketError:
    return PacketError(f"invalid sync snapshot: {message}")


def decode_sync_snapshot(payload: bytes | bytearray | list[int]) -> SyncSnapshot:
    raw = bytes(payload)
    if len(raw) < 8:
        raise _packet_error("payload is truncated")
    if raw[0] != SYNC_VERSION:
        raise _packet_error("unsupported version")

    mode = raw[1]
    if mode not in SUPPORTED_MODES:
        raise _packet_error("unsupported mode")
    color_count = raw[6]
    if color_count > MAX_SYNC_COLORS:
        raise _packet_error("too many colors")

    base_length = 8 + color_count * 3
    if len(raw) < base_length:
        raise _packet_error("color data is truncated")
    matrix_present = raw[base_length - 1]
    if matrix_present not in (0, 1):
        raise _packet_error("invalid matrix flag")
    expected_length = base_length + (MATRIX_BYTE_LENGTH if matrix_present else 0)
    if len(raw) != expected_length:
        raise _packet_error("invalid matrix length")

    colors = []
    offset = 7
    for _ in range(color_count):
        colors.append(tuple(raw[offset:offset + 3]))
        offset += 3

    offset += 1
    matrix = None
    if matrix_present:
        matrix_rows = []
        for _ in range(MATRIX_ROWS):
            row = []
            for _ in range(MATRIX_COLUMNS):
                row.append(tuple(raw[offset:offset + 3]))
                offset += 3
            matrix_rows.append(tuple(row))
        matrix = tuple(matrix_rows)

    try:
        return SyncSnapshot(
            mode=mode,
            brightness_min=raw[2],
            brightness_max=raw[3],
            timing=int.from_bytes(raw[4:6], "big"),
            colors=tuple(colors),
            matrix=matrix,
        )
    except ValueError as exc:
        raise _packet_error(str(exc)) from exc
