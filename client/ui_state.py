from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


UI_STATE_VERSION = 1
MATRIX_ROWS = 6
MATRIX_COLUMNS = 144
MAX_COLORS = 64
VALID_SOURCES = frozenset(("quick", "matrix"))
VALID_MODES = frozenset(("静态常亮", "呼吸渐变", "流光溢彩", "自定义矩阵"))


def _require_int(value, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


def _normalize_color(value, field: str) -> str:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        raise ValueError(f"{field} must be a six-digit hexadecimal color")
    try:
        int(value[1:], 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be a six-digit hexadecimal color") from exc
    return value.lower()


def _normalize_matrix(value) -> list[list[str]]:
    if not isinstance(value, list) or len(value) != MATRIX_ROWS:
        raise ValueError("matrix144x6 must contain six rows")
    matrix = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != MATRIX_COLUMNS:
            raise ValueError(f"matrix144x6 row {row_index} must contain 144 colors")
        matrix.append([
            _normalize_color(cell, f"matrix144x6[{row_index}]")
            for cell in row
        ])
    return matrix


def normalize_ui_state(state: dict) -> dict:
    if not isinstance(state, dict):
        raise ValueError("UI state must be an object")
    version = state.get("version")
    if version != UI_STATE_VERSION:
        raise ValueError("unsupported UI state version")

    source = state.get("source")
    if source not in VALID_SOURCES:
        raise ValueError("invalid UI output source")
    mode = state.get("mode")
    if mode == "彩虹跑马":
        mode = "流光溢彩"
    if mode not in VALID_MODES:
        raise ValueError("invalid UI mode")

    colors = state.get("colors")
    if not isinstance(colors, list) or not 1 <= len(colors) <= MAX_COLORS:
        raise ValueError("UI color list must contain between 1 and 64 colors")

    return {
        "version": UI_STATE_VERSION,
        "source": source,
        "mode": mode,
        "brightness": _require_int(state.get("brightness"), "brightness", 0, 100),
        "speed": _require_int(state.get("speed"), "speed", 10, 200),
        "colors": [_normalize_color(color, "colors[]") for color in colors],
        "paintColor": _normalize_color(state.get("paintColor"), "paintColor"),
        "matrix144x6": _normalize_matrix(state.get("matrix144x6")),
    }


class UiStateStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def load(self) -> dict | None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return normalize_ui_state(json.load(handle))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def save(self, state: dict) -> dict:
        normalized = normalize_ui_state(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(normalized, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
            return normalized
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
