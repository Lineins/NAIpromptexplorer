from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


class SettingsManager:
    """Load and persist application settings."""

    DEFAULT_FOLDER = r"C:\\Users\\kuron\\Downloads\\NAIv4.5画風"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: Dict[str, object] = {}
        self._ensure_directory()
        self.load()

    def _ensure_directory(self) -> None:
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}
        if "default_folder" not in self.data:
            self.data["default_folder"] = self.DEFAULT_FOLDER
        if "presets" not in self.data or not isinstance(self.data["presets"], list):
            self.data["presets"] = []

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            # Swallow errors to avoid crashing when saving fails.
            pass

    @property
    def default_folder(self) -> str:
        value = self.data.get("default_folder", self.DEFAULT_FOLDER)
        if isinstance(value, str) and value:
            return value
        return self.DEFAULT_FOLDER

    def set_default_folder(self, folder: str) -> None:
        self.data["default_folder"] = folder
        self.save()

    @property
    def presets(self) -> List[str]:
        presets = self.data.get("presets", [])
        if isinstance(presets, list):
            return [str(p) for p in presets]
        return []

    def add_preset(self, folder: str) -> None:
        normalized = str(Path(folder))
        presets = self.presets
        if normalized not in presets:
            presets.append(normalized)
            self.data["presets"] = presets
            self.save()

    def remove_preset(self, folder: str) -> None:
        presets = [p for p in self.presets if Path(p) != Path(folder)]
        self.data["presets"] = presets
        self.save()
