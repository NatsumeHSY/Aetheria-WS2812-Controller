from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any


ROWS = 6
COLUMNS = 144
BLACK = "#000000"


def _color(value: str) -> str:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise ValueError("color must be a six-digit hexadecimal value")
    try:
        int(value[1:], 16)
    except ValueError as error:
        raise ValueError("color must be a six-digit hexadecimal value") from error
    return value.lower()


def validate_matrix(matrix: list[list[str]]) -> list[list[str]]:
    if not isinstance(matrix, list) or len(matrix) != ROWS:
        raise ValueError("matrix must contain exactly six rows")

    normalized = []
    has_lit_cell = False
    for row in matrix:
        if not isinstance(row, list) or len(row) != COLUMNS:
            raise ValueError("each matrix row must contain exactly 144 colors")
        normalized_row = [_color(value) for value in row]
        has_lit_cell = has_lit_cell or any(value != BLACK for value in normalized_row)
        normalized.append(normalized_row)

    if not has_lit_cell:
        raise ValueError("matrix must contain at least one lit cell")
    return normalized


def _empty_mask() -> list[list[int]]:
    return [[0 for _ in range(COLUMNS)] for _ in range(ROWS)]


def _preset_mask(name: str) -> list[list[int]]:
    mask = _empty_mask()
    if name == "horizontal":
        mask[ROWS // 2] = [1] * COLUMNS
    elif name == "vertical":
        for row in mask:
            row[COLUMNS // 2] = 1
    elif name == "border":
        for column in range(COLUMNS):
            mask[0][column] = mask[ROWS - 1][column] = 1
        for row in range(ROWS):
            mask[row][0] = mask[row][COLUMNS - 1] = 1
    elif name == "checkerboard":
        for row in range(ROWS):
            for column in range(COLUMNS):
                mask[row][column] = (row + column) % 2
    elif name == "diagonal":
        for row in range(ROWS):
            mask[row][round(row * (COLUMNS - 1) / (ROWS - 1))] = 1
    elif name == "cross":
        for column in range(COLUMNS):
            mask[ROWS // 2][column] = 1
        for row in range(ROWS):
            mask[row][COLUMNS // 2] = 1
    else:
        raise ValueError(f"unknown preset: {name}")
    return mask


def preset_shapes() -> list[dict[str, Any]]:
    definitions = (
        ("preset-horizontal", "横线", "horizontal"),
        ("preset-vertical", "竖线", "vertical"),
        ("preset-border", "边框", "border"),
        ("preset-checkerboard", "棋盘格", "checkerboard"),
        ("preset-diagonal", "对角线", "diagonal"),
        ("preset-cross", "十字", "cross"),
    )
    return [
        {
            "id": shape_id,
            "name": label,
            "kind": "preset",
            "editable": False,
            "matrix": _preset_mask(key),
        }
        for shape_id, label, key in definitions
    ]


def materialize_preset(matrix_mask: list[list[int]], paint_color: str) -> list[list[str]]:
    color = _color(paint_color)
    if not isinstance(matrix_mask, list) or len(matrix_mask) != ROWS:
        raise ValueError("preset mask must contain exactly six rows")

    matrix = []
    for row in matrix_mask:
        if not isinstance(row, list) or len(row) != COLUMNS:
            raise ValueError("each preset row must contain exactly 144 cells")
        if any(value not in (0, 1) for value in row):
            raise ValueError("preset mask cells must be 0 or 1")
        matrix.append([color if value else BLACK for value in row])
    return matrix


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


class MatrixShapeStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._users = self._load_users()

    def _load_users(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
        except (OSError, ValueError, json.JSONDecodeError):
            return []

        users = []
        for shape in raw:
            try:
                if not isinstance(shape, dict) or not str(shape.get("id", "")).startswith("user-"):
                    continue
                name = self._validate_name(shape.get("name"))
                matrix = validate_matrix(shape.get("matrix"))
            except (TypeError, ValueError):
                continue
            users.append({
                "id": str(shape["id"]),
                "name": name,
                "kind": "user",
                "editable": True,
                "matrix": matrix,
            })
        return users

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f"{self.path.stem}-",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(self._users, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("shape name is required")
        normalized = name.strip()
        if not normalized or len(normalized) > 40:
            raise ValueError("shape name must contain 1 to 40 characters")
        return normalized

    def list_shapes(self) -> list[dict[str, Any]]:
        return _copy(preset_shapes() + self._users)

    def get_shape(self, shape_id: str) -> dict[str, Any] | None:
        for shape in self.list_shapes():
            if shape["id"] == shape_id:
                return shape
        return None

    def save_user_shape(self, name: str, matrix: list[list[str]]) -> dict[str, Any]:
        shape = {
            "id": f"user-{uuid.uuid4().hex}",
            "name": self._validate_name(name),
            "kind": "user",
            "editable": True,
            "matrix": validate_matrix(matrix),
        }
        self._users.append(shape)
        self._persist()
        return _copy(shape)

    def _find_user(self, shape_id: str) -> dict[str, Any]:
        for shape in self._users:
            if shape["id"] == shape_id:
                return shape
        raise ValueError("shape is not an editable user shape")

    def update_user_shape(self, shape_id: str, name: str, matrix: list[list[str]]) -> dict[str, Any]:
        shape = self._find_user(shape_id)
        shape["name"] = self._validate_name(name)
        shape["matrix"] = validate_matrix(matrix)
        self._persist()
        return _copy(shape)

    def delete_user_shape(self, shape_id: str) -> None:
        shape = self._find_user(shape_id)
        self._users.remove(shape)
        self._persist()
