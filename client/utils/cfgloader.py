import json
import os
from pathlib import Path

CONFIG_DIR = os.path.join(Path(__file__).absolute().parent.parent, "configs")

class ConfigLoader:
    def __init__(self, filename: str) -> None:
        if "/" in filename or "\\" in filename:
            raise ValueError("Invalid filename")
        self.config_path = os.path.join(CONFIG_DIR, filename)

    def read_config(self) -> dict | list | None:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_config(self, data: dict | list) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)